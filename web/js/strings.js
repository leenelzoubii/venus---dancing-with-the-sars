/*
 * All user-visible text lives in this file, so copy can be edited without touching logic.
 * Structure: window.VENUS_STRINGS = { en: { key: "text" } }. Add an "ar" block later with the same keys
 * (Arabic text as \uXXXX escapes, and <html dir="rtl"> when the locale is "ar").
 * Keys are read by ui.js; a missing key shows the key name, so gaps are visible, never silent.
 */
window.VENUS_STRINGS = {
  en: {
    app_title: "Seeing the Dead Sea through the clouds",
    app_mark: "Team Venus",
    app_tagline: "NISAR L-band radar, Dead Sea east shore, Jordan",
    badge_provisional: "PROVISIONAL DATA",
    skip_to_map: "Skip to the map",
    map_label: "Map of the Dead Sea east shore showing NISAR radar layers",
    controls_label: "Layer and date controls",
    panel_label: "Legend, layer information and limitations",
    footer_label: "Data credit and licence",

    layer_group: "Layer",
    layer_backscatter: "Radar backscatter",
    layer_change: "Change map",
    layer_water: "Water mask (HV)",
    pol_group: "Polarization",
    pol_hv: "HV",
    pol_hh: "HH",
    pol_hv_hint: "HV: the water channel",
    pol_hh_hint: "HH: surface and structure, comparison only",
    date_label: "Acquisition date",
    date_reference: "reference",

    legend_title: "Legend",
    legend_backscatter: "Radar backscatter, gamma-0 power in dB",
    legend_backscatter_caption: "Dark = smooth (water). Bright = rough or textured (shore, salt crust, plain).",
    legend_change: "Change in echo strength (dB), after offset removal",
    legend_change_caption: "Blue = less echo than on the reference date. Orange = more echo. Near-zero change is transparent.",
    legend_water: "Open water, method B (cyan) and detection-limit band (amber)",
    legend_water_caption: "Cyan: open water by the primary method. Amber: pixels that flip inside the +/-1.5 dB threshold band.",

    water_hh_note: "Water cannot be mapped in HH: open water and the bright land tail overlap in HH backscatter, so no single HH threshold separates them. Switch to HV for the water mask.",
    change_reference_note: "This is the reference date, so there is no change to show. Pick a later date.",
    basemap_attribution: "Basemap: Esri, Vantor, Earthstar Geographics, GIS User Community",
    basemap_unavailable: "Basemap unavailable offline; radar layers still work.",

    info_title: "Layer information",
    info_intro: "Everything below is read from the data manifest for the layer you are viewing.",
    info_date: "Date",
    info_reference: "Reference date",
    info_product: "Product",
    info_crid: "CRID and maturity",
    info_track: "Geometry",
    info_pol: "Polarization",
    info_crs: "Coordinate systems",
    info_scale: "Colour scale",
    info_offset: "Scene offset removed",
    info_multilook: "Display resolution",
    info_steps: "Processing steps",
    info_water_stats: "Water area for this date",
    info_area: "Open water",
    info_band: "Threshold band",
    info_threshold: "Threshold",
    info_none: "Not applicable to this layer.",

    whatis_title: "What am I looking at?",
    whatis_body: "This is radar, not a photograph. The satellite sends a pulse and measures what comes back. Smooth open water sends it away, so it looks dark. Rough ground sends some back, so it looks bright. Radar works through cloud and at night, which is why it can show the lake when optical images cannot.",

    detection_title: "How sure are these numbers?",
    detection_body_fallback: "The detection summary will appear here once the water statistics are loaded.",

    limits_title: "Limitations, stated plainly",
    limits_body: "Only one satellite track is used, so every date is seen from the same angle. Data are PROVISIONAL and may be reprocessed. Wind roughens water and makes it brighter. Salt crust can also look bright. Each water area carries a threshold band, shown in the detection panel. Change smaller than the uncertainty is not reported as change. Hypotheses about causes are not findings.",

    about_title: "About and data",
    footer_credit_label: "Data credit",
    footer_licence: "Code licence: see the LICENSE file in the repository.",
    footer_nonendorsement: "NASA does not endorse any non-U.S. Government entity or this project.",

    story_title: "Story mode",
    story_placeholder: "Guided story steps arrive in the next build. For now, use the layer, polarization and date controls.",

    notice_label: "Notice",
    error_no_data: "The data manifest did not load. Check that web/data/manifest.js is next to index.html.",
    error_layer: "Could not load {name}. Check that the web/data/layers folder is next to index.html.",
    debug_on: "Debug mode is on: bounds, crosshair and opacity controls are shown.",
    debug_opacity: "Overlay opacity",
    debug_bounds: "Show overlay bounds",
    debug_crosshair: "Show crosshair",

    units_db: "dB",
    units_km2: "km2"
  }
};
