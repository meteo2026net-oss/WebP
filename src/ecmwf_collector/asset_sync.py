"""Consent-gated asset registration and at-least-once Outbox replication."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from .connection_profiles import DatabaseProfileStore
from .database_routing import DatabaseRoutingError, DatabaseRoutingStore
from .file_asset_catalog import FileAssetCatalog, FileAssetError, asset_from_sidecar


class CatalogApprovalError(PermissionError):
    """A required explicit database-write approval is missing or mismatched."""


@dataclass(frozen=True)
class CatalogWriteApproval:
    """Ephemeral approval produced only after a UI confirmation for this route.

    The approval is intentionally not persisted: after an application restart,
    a new explicit confirmation is required before another database write.
    """
    destination_profile_id: str
    schema_approved_profile_ids: tuple[str, ...]
    replica_profile_ids: tuple[str, ...] = ()
    asset_write_confirmed: bool = False


@dataclass(frozen=True)
class OutboxSyncApproval:
    """Explicit per-run authorization for the replica databases to be written."""
    target_profile_ids: tuple[str, ...]
    confirmed: bool = False


class ApprovedCatalogSink:
    """Connector callback that writes only to the explicitly routed/approved DB."""

    def __init__(
        self,
        profile_store: DatabaseProfileStore,
        routing_store: DatabaseRoutingStore,
        secrets,
        approval: CatalogWriteApproval,
    ):
        self.profile_store = profile_store
        self.routing_store = routing_store
        self.secrets = secrets
        self.approval = approval
        if not approval.asset_write_confirmed:
            raise CatalogApprovalError("لم تصدر موافقة صريحة على تسجيل أصول الملفات.")
        if approval.destination_profile_id not in approval.schema_approved_profile_ids:
            raise CatalogApprovalError("الموافقة لا تشمل إنشاء/تهيئة مخطط قاعدة الوجهة.")
        if len(set(approval.replica_profile_ids)) != len(approval.replica_profile_ids):
            raise CatalogApprovalError("قائمة قواعد المزامنة تحتوي على تكرار.")
        if approval.destination_profile_id in approval.replica_profile_ids:
            raise CatalogApprovalError("قاعدة الوجهة الأساسية لا يمكن تكرارها كوجهة ثانوية.")
        if not set(approval.replica_profile_ids).issubset(set(approval.schema_approved_profile_ids)):
            raise CatalogApprovalError("يلزم اعتماد تهيئة مخطط كل قاعدة ثانوية قبل إضافتها إلى Outbox.")

    def register_sidecar(self, sidecar_path: Path) -> dict:
        asset = asset_from_sidecar(Path(sidecar_path))
        route_key = self.routing_store.model_key(
            asset.provider_id, asset.model_id, asset.product_id
        )
        try:
            routed_profile_id = self.routing_store.resolve(route_key)
        except DatabaseRoutingError:
            raise
        if routed_profile_id is None:
            raise CatalogApprovalError(
                f"لا يوجد مسار صريح للنموذج/المنتج {route_key}؛ لم تتم الكتابة."
            )
        if routed_profile_id != self.approval.destination_profile_id:
            raise CatalogApprovalError(
                "قاعدة الوجهة المعتمدة لا تطابق مسار النموذج الحالي؛ لم تتم الكتابة."
            )

        profile_ids = (routed_profile_id, *self.approval.replica_profile_ids)
        profiles = {}
        for profile_id in profile_ids:
            profile = self.profile_store.get(profile_id)
            if profile is None or not profile.enabled:
                raise CatalogApprovalError(
                    f"اتصال قاعدة البيانات {profile_id} غير موجود أو معطّل؛ لم تتم الكتابة."
                )
            if profile_id not in self.approval.schema_approved_profile_ids:
                raise CatalogApprovalError("لا توجد موافقة على تهيئة مخطط إحدى قواعد البيانات.")
            profiles[profile_id] = profile

        # DDL is executed only because the explicit approval object includes
        # every profile that may receive schema creation.
        for profile_id in profile_ids:
            FileAssetCatalog(profiles[profile_id], self.secrets).initialize_schema()

        primary = FileAssetCatalog(profiles[routed_profile_id], self.secrets)
        return primary.register_asset(
            asset, replica_profile_ids=self.approval.replica_profile_ids
        )


class AssetOutboxSynchronizer:
    """At-least-once replication; target writes are idempotent by asset_key."""

    def __init__(self, source_profile_id: str, profile_store: DatabaseProfileStore, secrets):
        source = profile_store.get(source_profile_id)
        if source is None or not source.enabled:
            raise CatalogApprovalError("قاعدة المصدر غير موجودة أو معطّلة.")
        self.source_profile_id = source_profile_id
        self.profile_store = profile_store
        self.secrets = secrets
        self.source_catalog = FileAssetCatalog(source, secrets)

    def sync_pending(self, approval: OutboxSyncApproval, *, limit: int = 100) -> dict:
        if not approval.confirmed:
            raise CatalogApprovalError("يلزم تأكيد صريح قبل كتابة قواعد المزامنة.")
        allowed = set(approval.target_profile_ids)
        if self.source_profile_id in allowed:
            raise CatalogApprovalError("قاعدة المصدر لا يمكن أن تكون وجهة مزامنة لنفسها.")
        pending = self.source_catalog.pending_outbox(limit=limit)
        result = {"delivered": 0, "failed": 0, "skipped": 0, "items": []}
        for event in pending:
            target_id = event["target_profile_id"]
            if target_id not in allowed:
                result["skipped"] += 1
                continue
            target_profile = self.profile_store.get(target_id)
            if target_profile is None or not target_profile.enabled:
                error = "TargetProfileUnavailable"
                self.source_catalog.finish_outbox(event["event_id"], delivered=False, error=error)
                result["failed"] += 1
                result["items"].append({"event_id": event["event_id"], "status": "failed", "error": error})
                continue
            try:
                target_catalog = FileAssetCatalog(target_profile, self.secrets)
                variants = self.source_catalog.load_asset_variants(event["asset_key"])
                # No replica IDs are passed: replication must not fan out or
                # create loops. A crash before source acknowledgement is safe:
                # the target's unique asset_key makes the retry idempotent.
                for asset in variants:
                    target_catalog.register_asset(asset)
                self.source_catalog.finish_outbox(event["event_id"], delivered=True)
                result["delivered"] += 1
                result["items"].append({"event_id": event["event_id"], "status": "delivered"})
            except Exception as exc:
                # Persist exception class only; driver exceptions can contain
                # connection details and must not leak into the Outbox.
                error = type(exc).__name__
                self.source_catalog.finish_outbox(event["event_id"], delivered=False, error=error)
                result["failed"] += 1
                result["items"].append({"event_id": event["event_id"], "status": "failed", "error": error})
        return result
