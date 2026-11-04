(() => {
  const map = L.map("map", { zoomControl: true }).setView([32, 36], 5);
  L.tileLayer("https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png", {
    maxZoom: 18,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
  }).addTo(map);

  const select = document.getElementById("layerSelect");
  const info = document.getElementById("layerInfo");
  const status = document.getElementById("status");
  const opacity = document.getElementById("opacity");
  const opacityValue = document.getElementById("opacityValue");
  let entries = [];
  let activeLayer = null;
  let activeEntry = null;

  function setStatus(message) { status.textContent = message; }
  function showEntry(entry) {
    if (activeLayer) map.removeLayer(activeLayer);
    activeEntry = entry;
    const b = entry.bounds;
    const bounds = [[b.south, b.west], [b.north, b.east]];
    activeLayer = L.imageOverlay("../output/map_data/" + encodeURIComponent(entry.image), bounds, {
      opacity: Number(opacity.value) / 100,
      interactive: false
    }).addTo(map);
    map.fitBounds(bounds);
    document.getElementById("legendMin").textContent = Number(entry.value_min).toPrecision(3) + " " + (entry.units || "");
    document.getElementById("legendMax").textContent = Number(entry.value_max).toPrecision(3) + " " + (entry.units || "");
    info.textContent = [
      entry.long_name || entry.variable || "Weather field",
      "الوحدة: " + (entry.units || "غير معروفة"),
      "وقت الصلاحية: " + (entry.valid_time || "غير محدد"),
      "المدى: " + Number(entry.value_min).toFixed(2) + " إلى " + Number(entry.value_max).toFixed(2),
      "الخلايا الصالحة: " + (entry.valid_cells ?? "—")
    ].join(" | ");
    setStatus("تم تحميل الطبقة: " + (entry.variable || entry.image));
  }
  async function loadManifest() {
    setStatus("جارٍ قراءة قائمة الطبقات…");
    try {
      const response = await fetch("../output/map_data/manifest.json?t=" + Date.now());
      if (!response.ok) throw new Error("لم يتم العثور على output/map_data/manifest.json");
      const manifest = await response.json();
      entries = Array.isArray(manifest.layers) ? manifest.layers : [];
      select.replaceChildren();
      if (!entries.length) {
        select.add(new Option("لا توجد طبقات بعد", ""));
        info.textContent = "شغّل أداة معالجة GRIB أولاً لإنشاء الطبقات.";
        setStatus("البيان الوصفي موجود لكنه لا يحتوي طبقات.");
        return;
      }
      entries.forEach((entry, index) => {
        const label = [entry.variable || "field", entry.typeOfLevel || "", entry.level ?? "", entry.units || "", entry.valid_time || "", entry.step !== undefined ? "step " + entry.step : ""].filter(x => x !== "" && x !== null && x !== undefined).join(" — ");
        select.add(new Option(label, String(index)));
      });
      select.value = "0";
      showEntry(entries[0]);
      setStatus("تم العثور على " + entries.length + " طبقة.");
    } catch (error) {
      select.replaceChildren(new Option("لا توجد طبقات جاهزة", ""));
      info.textContent = "بعد تنزيل GRIB ومعالجته ستظهر الطبقات هنا.";
      setStatus(error.message + " — افتح الخادم من جذر المستودع.");
    }
  }


  let pointRequest = 0;
  map.on("click", async (event) => {
    if (!activeEntry) return;
    const panel = document.getElementById("pointInfo");
    const requestId = ++pointRequest;
    const lat = event.latlng.lat;
    const lon = event.latlng.lng;
    panel.textContent = "جارٍ استخراج أقرب قيمة شبكية…";
    try {
      const params = new URLSearchParams({
        image: activeEntry.image,
        lat: lat.toFixed(6),
        lon: lon.toFixed(6)
      });
      const response = await fetch("/api/point?" + params.toString());
      const result = await response.json();
      if (requestId !== pointRequest) return;
      if (!response.ok) throw new Error(result.error || "تعذّر استخراج القيمة.");
      const valueText = result.valid
        ? Number(result.value).toFixed(3) + " " + (result.units || "")
        : (result.message || "لا توجد قيمة صالحة في أقرب خلية.");
      panel.textContent = [
        result.long_name || result.variable || "الحقل الجوي",
        "القيمة: " + valueText,
        "إحداثيات الخلية: " + Number(result.latitude).toFixed(4) + ", " + Number(result.longitude).toFixed(4),
        "الإحداثيات المطلوبة: " + lat.toFixed(4) + ", " + lon.toFixed(4),
        "الصلاحية: " + (result.valid_time || "غير محددة")
      ].join(" | ");
    } catch (error) {
      if (requestId === pointRequest) panel.textContent = error.message;
    }
  });

  select.addEventListener("change", () => {
    const entry = entries[Number(select.value)];
    if (entry) showEntry(entry);
  });
  opacity.addEventListener("input", () => {
    opacityValue.value = opacity.value + "%";
    if (activeLayer) activeLayer.setOpacity(Number(opacity.value) / 100);
  });
  document.getElementById("fitButton").addEventListener("click", () => {
    if (activeEntry) {
      const b = activeEntry.bounds;
      map.fitBounds([[b.south, b.west], [b.north, b.east]]);
    }
  });
  document.getElementById("reloadButton").addEventListener("click", loadManifest);
  loadManifest();
})();
