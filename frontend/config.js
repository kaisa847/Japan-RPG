const CONFIG = {
    API_BASE_URL: window.location.origin,
    CANVAS_WIDTH: 1920,
    CANVAS_HEIGHT: 1080,
    TYPEWRITER_SPEED_MS: 30,
    FADE_TRANSITION_MS: 300,
    DEFAULT_EXPRESSION: "neutral",
    DEFAULT_BACKGROUND: "apartment",
    MAX_SAVE_SLOTS: 9,
    MAX_SCENE_HISTORY: 100,
    // Treat the on-screen keyboard as open when the visual viewport shrinks
    // by more than this many pixels.
    KEYBOARD_OPEN_THRESHOLD_PX: 150,
    ASSET_PATHS: {
        characters: "/assets/characters",
        backgrounds: "/assets/backgrounds",
    },
    CHARACTER_NAMES: {
        aoi: "Aoi",
    },
    AFFECTION_TONES: {
        distant:  { label: "Distanziert", color: "#888888" },
        neutral:  { label: "Neutral",     color: "#aaaaaa" },
        friendly: { label: "Freundlich",  color: "#66ccaa" },
        warm:     { label: "Warmherzig",  color: "#ffaa44" },
        intimate: { label: "Vertraut",    color: "#ff6666" },
    },
    TTS: {
        ENABLED_BY_DEFAULT: true,
        LOCAL_STORAGE_KEY: "tts_enabled",
        MAX_TEXT_LENGTH: 200,
        STATUS_RECHECK_MS: 5000,
    },
};
