class VNEngine {
    constructor() {
        // Core elements
        this.backgroundLayer = document.getElementById("background-layer");
        this.backgroundMissingLabel = document.getElementById("background-missing-label");
        this.characterSprite = document.getElementById("character-sprite");
        this.characterMissingLabel = document.getElementById("character-missing-label");
        this.characterName = document.getElementById("character-name");
        this.dialogText = document.getElementById("dialog-text");
        this.translationText = document.getElementById("translation-text");
        this.translationToggle = document.getElementById("translation-toggle");
        this.furiganaToggle = document.getElementById("furigana-toggle");
        this.hintToggle = document.getElementById("hint-toggle");
        this.userInput = document.getElementById("user-input");
        this.sendButton = document.getElementById("send-button");
        this.continueButton = document.getElementById("continue-button");
        this.loadingOverlay = document.getElementById("loading-overlay");

        // HUD elements
        this.hudDay = document.getElementById("hud-day");
        this.hudHour = document.getElementById("hud-hour");
        this.hudAffectionIcon = document.getElementById("hud-affection-icon");
        this.hudAffectionLabel = document.getElementById("hud-affection-label");

        // Error correction hint
        this.errorCorrectionHint = document.getElementById("error-correction-hint");

        // Scene-end choices
        this.sceneEndChoices = document.getElementById("scene-end-choices");

        // Navigation buttons (HUD + textbox header)
        this.backButton = document.getElementById("back-button");
        this.historyButton = document.getElementById("history-button");
        this.menuButton = document.getElementById("menu-button");
        this.statsButton = document.getElementById("stats-button");

        // Name entry overlay
        this.nameEntryOverlay = document.getElementById("name-entry-overlay");
        this.nameEntryInput = document.getElementById("name-entry-input");
        this.nameEntrySubmit = document.getElementById("name-entry-submit");
        this.nameEntryError = document.getElementById("name-entry-error");

        // Menu overlay
        this.menuOverlay = document.getElementById("menu-overlay");
        this.menuCloseButton = document.getElementById("menu-close-button");
        this.saveSlotsContainer = document.getElementById("save-slots-container");
        this.newGameButton = document.getElementById("new-game-button");
        this.menuPlayerNameInput = document.getElementById("menu-player-name-input");
        this.menuPlayerNameSave = document.getElementById("menu-player-name-save");
        this.menuPlayerNameStatus = document.getElementById("menu-player-name-status");

        // Scenario elements
        this.menuScenarioInput = document.getElementById("menu-scenario-input");
        this.menuScenarioSave = document.getElementById("menu-scenario-save");
        this.menuScenarioReset = document.getElementById("menu-scenario-reset");
        this.menuScenarioStatus = document.getElementById("menu-scenario-status");

        // Admin elements
        this.adminSection = document.getElementById("admin-section");
        this.adminRestartButton = document.getElementById("admin-restart-button");
        this.adminRestartStatus = document.getElementById("admin-restart-status");

        // History overlay
        this.historyOverlay = document.getElementById("history-overlay");
        this.historyCloseButton = document.getElementById("history-close-button");
        this.historyEntries = document.getElementById("history-entries");

        // Stats overlay
        this.statsOverlay = document.getElementById("stats-overlay");
        this.statsCloseButton = document.getElementById("stats-close-button");
        this.statsAffectionSection = document.getElementById("stats-affection-section");
        this.statsLearningSection = document.getElementById("stats-learning-section");

        // Voice toggle buttons
        this.voiceToggle = document.getElementById("voice-toggle");

        // State
        this.currentScene = null;
        this.isLoading = false;
        this.showTranslation = false;
        this.showFurigana = true;
        this.showHints = true;
        this.typewriterTimeout = null;
        this.assetCache = new Map();
        this.availableAssets = null;
        this.startPrompt = "(Spielstart)";

        // Scene history for back-button navigation
        this.sceneHistory = [];
        this.sceneHistoryIndex = -1;

        // Cached game state data (affection, learning, time)
        this.lastAffection = null;
        this.lastLearning = null;
        this.lastTime = null;
        this.playerName = "";
        this.isAdmin = false;

        // TTS state
        this.ttsAvailable = false;
        this.ttsEnabled = this._loadTTSPreference();
        this._audioContext = null;
        this._currentSource = null;
        this._lastTTSText = null;
        this._lastTTSExpression = null;

        // Voice replay button
        this.voiceReplay = document.getElementById("voice-replay");

        this._bindEvents();
        this._init();
    }

    // --- Initialization ---

    async _init() {
        console.log("[VNEngine] Initializing...");

        // Auth check — redirect to login if no token
        if (!Auth.isLoggedIn()) {
            Auth.redirectToLogin();
            return;
        }

        // Verify token is still valid
        try {
            const meResp = await Auth.fetchAuthenticated(`${CONFIG.API_BASE_URL}/api/auth/me`);
            if (!meResp.ok) {
                Auth.logout();
                return;
            }
            const meData = await meResp.json();
            this._setUsername(meData.username);
            this.playerName = meData.player_name || "";
            this.isAdmin = !!meData.is_admin;
        } catch (e) {
            console.warn("[VNEngine] Auth verification failed:", e);
            return;
        }

        // If no player name is set, require it before starting the game
        if (!this.playerName) {
            this._showNameEntry();
            return;
        }

        await this._startGame();
    }

    async _startGame() {
        try {
            await Promise.all([
                this._fetchAvailableAssets(),
                this._fetchStartPrompt(),
                this._checkTTSAvailability(),
            ]);

            const restored = await this._tryRestoreLastScene();
            if (restored) {
                console.log("[VNEngine] Restored last scene from saved state.");
            } else {
                console.log("[VNEngine] No saved state, starting new game.");
                await this.sendInput(this.startPrompt);
            }
        } catch (e) {
            console.error("[VNEngine] Init failed:", e);
            this._setLoading(false);
        }
    }

    _setUsername(username) {
        const el = document.getElementById("user-display");
        if (el) el.textContent = username;
    }

    // --- Player Name Entry ---

    _showNameEntry() {
        this.nameEntryOverlay.classList.remove("hidden");
        this.nameEntryInput.value = "";
        this.nameEntryError.textContent = "";
        this.nameEntryInput.focus();
    }

    async _onNameEntrySubmit() {
        const name = this.nameEntryInput.value.trim();
        this.nameEntryError.textContent = "";

        if (!name) {
            this.nameEntryError.textContent = "Bitte einen Spielernamen eingeben.";
            return;
        }
        if (name.length > 30) {
            this.nameEntryError.textContent = "Maximal 30 Zeichen erlaubt.";
            return;
        }

        try {
            const resp = await Auth.fetchAuthenticated(`${CONFIG.API_BASE_URL}/api/player_name`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ player_name: name }),
            });
            if (!resp.ok) {
                const data = await resp.json().catch(() => ({}));
                this.nameEntryError.textContent = data.detail || "Fehler beim Speichern.";
                return;
            }
            this.playerName = name;
            this.nameEntryOverlay.classList.add("hidden");
            await this._startGame();
        } catch (e) {
            this.nameEntryError.textContent = "Verbindungsfehler.";
        }
    }

    async _onMenuPlayerNameSave() {
        const name = this.menuPlayerNameInput.value.trim();
        this.menuPlayerNameStatus.textContent = "";
        this.menuPlayerNameStatus.style.color = "";

        if (!name) {
            this.menuPlayerNameStatus.textContent = "Name darf nicht leer sein.";
            this.menuPlayerNameStatus.style.color = "#e08080";
            return;
        }
        if (name.length > 30) {
            this.menuPlayerNameStatus.textContent = "Maximal 30 Zeichen.";
            this.menuPlayerNameStatus.style.color = "#e08080";
            return;
        }

        try {
            const resp = await Auth.fetchAuthenticated(`${CONFIG.API_BASE_URL}/api/player_name`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ player_name: name }),
            });
            if (!resp.ok) {
                const data = await resp.json().catch(() => ({}));
                this.menuPlayerNameStatus.textContent = data.detail || "Fehler.";
                this.menuPlayerNameStatus.style.color = "#e08080";
                return;
            }
            this.playerName = name;
            this.menuPlayerNameStatus.textContent = "Gespeichert!";
            this.menuPlayerNameStatus.style.color = "#80c080";
        } catch (e) {
            this.menuPlayerNameStatus.textContent = "Verbindungsfehler.";
            this.menuPlayerNameStatus.style.color = "#e08080";
        }
    }

    // --- Scenario Management ---

    async _loadScenario() {
        try {
            const resp = await Auth.fetchAuthenticated(`${CONFIG.API_BASE_URL}/api/scenario`);
            if (resp.ok) {
                const data = await resp.json();
                this.menuScenarioInput.value = data.scenario || "";
            }
        } catch (e) {
            console.warn("[VNEngine] Could not load scenario:", e);
        }
    }

    async _onScenarioSave() {
        const scenario = this.menuScenarioInput.value.trim();
        this.menuScenarioStatus.textContent = "";
        this.menuScenarioStatus.style.color = "";

        if (!scenario) {
            this.menuScenarioStatus.textContent = "Szenario darf nicht leer sein.";
            this.menuScenarioStatus.style.color = "#e08080";
            return;
        }
        if (scenario.length > 5000) {
            this.menuScenarioStatus.textContent = "Maximal 5000 Zeichen.";
            this.menuScenarioStatus.style.color = "#e08080";
            return;
        }

        try {
            const resp = await Auth.fetchAuthenticated(`${CONFIG.API_BASE_URL}/api/scenario`, {
                method: "PUT",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ scenario }),
            });
            if (!resp.ok) {
                const data = await resp.json().catch(() => ({}));
                this.menuScenarioStatus.textContent = data.detail || "Fehler.";
                this.menuScenarioStatus.style.color = "#e08080";
                return;
            }
            this.menuScenarioStatus.textContent = "Gespeichert! Starte ein neues Spiel, um das Szenario zu verwenden.";
            this.menuScenarioStatus.style.color = "#80c080";
            // Re-fetch start prompt so a new game uses the updated scenario
            await this._fetchStartPrompt();
        } catch (e) {
            this.menuScenarioStatus.textContent = "Verbindungsfehler.";
            this.menuScenarioStatus.style.color = "#e08080";
        }
    }

    async _onScenarioReset() {
        this.menuScenarioStatus.textContent = "";
        this.menuScenarioStatus.style.color = "";

        try {
            const resp = await Auth.fetchAuthenticated(`${CONFIG.API_BASE_URL}/api/scenario/reset`, {
                method: "POST",
            });
            if (resp.ok) {
                const data = await resp.json();
                this.menuScenarioInput.value = data.scenario || "";
                this.menuScenarioStatus.textContent = "Auf Standard zurückgesetzt.";
                this.menuScenarioStatus.style.color = "#80c080";
                await this._fetchStartPrompt();
            }
        } catch (e) {
            this.menuScenarioStatus.textContent = "Verbindungsfehler.";
            this.menuScenarioStatus.style.color = "#e08080";
        }
    }

    // --- Admin: Server Restart ---

    async _onAdminRestart() {
        if (!confirm("Server aktualisieren und neustarten? Alle Spieler werden kurzzeitig getrennt.")) {
            return;
        }
        this.adminRestartButton.disabled = true;
        this.adminRestartStatus.textContent = "Git pull wird ausgeführt...";
        this.adminRestartStatus.style.color = "";

        try {
            const resp = await Auth.fetchAuthenticated(`${CONFIG.API_BASE_URL}/api/admin/restart`, {
                method: "POST",
            });
            if (!resp.ok) {
                const data = await resp.json().catch(() => ({}));
                this.adminRestartStatus.textContent = data.detail || "Fehler beim Neustart.";
                this.adminRestartStatus.style.color = "#e08080";
                this.adminRestartButton.disabled = false;
                return;
            }
            const data = await resp.json();
            if (!data.success) {
                this.adminRestartStatus.textContent = `Fehler bei ${data.phase}: ${data.output}`;
                this.adminRestartStatus.style.color = "#e08080";
                this.adminRestartButton.disabled = false;
                return;
            }
            this.adminRestartStatus.textContent = `Update erfolgreich. Server wird neugestartet...\n${data.output}`;
            this.adminRestartStatus.style.color = "#80c080";

            // Wait for restart then reload page
            setTimeout(() => {
                this.adminRestartStatus.textContent += "\nSeite wird neu geladen...";
                setTimeout(() => { window.location.reload(); }, 3000);
            }, 3000);
        } catch (e) {
            this.adminRestartStatus.textContent = "Verbindungsfehler.";
            this.adminRestartStatus.style.color = "#e08080";
            this.adminRestartButton.disabled = false;
        }
    }

    async _tryRestoreLastScene() {
        try {
            const response = await Auth.fetchAuthenticated(`${CONFIG.API_BASE_URL}/game_state`);
            if (!response.ok) {
                console.warn("[VNEngine] /game_state returned", response.status);
                return false;
            }

            const state = await response.json();
            console.log("[VNEngine] game_state:", { has_history: state.has_history, has_last_scene: !!state.last_scene });

            // Cache game state data for HUD and stats
            if (state.affection) this.lastAffection = state.affection;
            if (state.learning) this.lastLearning = state.learning;
            if (state.time) this.lastTime = state.time;

            // Update HUD with restored state
            this._updateHUD(state.time, state.affection);

            if (state.has_history && state.last_scene) {
                // Load scene history from backend
                await this._loadSceneHistory();
                await this._renderScene(state.last_scene, { skipTypewriter: true });
                if (!state.last_scene.character) this._showNarratorContinue();
                return true;
            }
        } catch (e) {
            console.warn("[VNEngine] Could not restore last scene:", e);
        }
        return false;
    }

    async _loadSceneHistory() {
        try {
            const response = await Auth.fetchAuthenticated(`${CONFIG.API_BASE_URL}/api/scene_history`);
            if (response.ok) {
                const data = await response.json();
                this.sceneHistory = data.scenes || [];
                this.sceneHistoryIndex = this.sceneHistory.length - 1;
                console.log(`[VNEngine] Loaded ${this.sceneHistory.length} scene history entries.`);
            }
        } catch (e) {
            console.warn("[VNEngine] Could not load scene history:", e);
        }
    }

    // --- Event Binding ---

    _bindEvents() {
        this.sendButton.addEventListener("click", () => this._onSend());
        this.continueButton.addEventListener("click", () => this._onContinue());
        this.userInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter" && !this.isLoading) this._onSend();
        });
        this.translationToggle.addEventListener("click", () => this._toggleTranslation());
        this.furiganaToggle.addEventListener("click", () => this._toggleFurigana());
        this.hintToggle.addEventListener("click", () => this._toggleHints());

        // Toolbar buttons
        this.backButton.addEventListener("click", () => this._onBack());
        this.historyButton.addEventListener("click", () => this._openHistory());
        this.menuButton.addEventListener("click", () => this._openMenu());
        this.statsButton.addEventListener("click", () => this._openStats());

        // Voice toggle & replay
        this.voiceToggle.addEventListener("click", () => this._toggleVoice());
        this.voiceReplay.addEventListener("click", () => this._replayTTS());

        // Keyboard detection via visualViewport API
        this._initKeyboardDetection();

        // Name entry overlay
        this.nameEntrySubmit.addEventListener("click", () => this._onNameEntrySubmit());
        this.nameEntryInput.addEventListener("keydown", (e) => {
            if (e.key === "Enter") this._onNameEntrySubmit();
        });

        // Menu overlay
        this.menuCloseButton.addEventListener("click", () => this._closeMenu());
        this.newGameButton.addEventListener("click", () => this._onNewGame());
        this.menuPlayerNameSave.addEventListener("click", () => this._onMenuPlayerNameSave());
        this.menuScenarioSave.addEventListener("click", () => this._onScenarioSave());
        this.menuScenarioReset.addEventListener("click", () => this._onScenarioReset());

        // Admin restart
        this.adminRestartButton.addEventListener("click", () => this._onAdminRestart());

        // Logout
        const logoutBtn = document.getElementById("logout-button");
        if (logoutBtn) logoutBtn.addEventListener("click", () => Auth.logout());
        this.menuOverlay.addEventListener("click", (e) => {
            if (e.target === this.menuOverlay) this._closeMenu();
        });

        // History overlay
        this.historyCloseButton.addEventListener("click", () => this._closeHistory());
        this.historyOverlay.addEventListener("click", (e) => {
            if (e.target === this.historyOverlay) this._closeHistory();
        });

        // Stats overlay
        this.statsCloseButton.addEventListener("click", () => this._closeStats());
        this.statsOverlay.addEventListener("click", (e) => {
            if (e.target === this.statsOverlay) this._closeStats();
        });

        // Keyboard: Escape closes overlays
        document.addEventListener("keydown", (e) => {
            if (e.key === "Escape") {
                if (!this.menuOverlay.classList.contains("hidden")) {
                    this._closeMenu();
                } else if (!this.historyOverlay.classList.contains("hidden")) {
                    this._closeHistory();
                } else if (!this.statsOverlay.classList.contains("hidden")) {
                    this._closeStats();
                }
            }
        });

        // Furigana and hints are on by default
        this.furiganaToggle.classList.add("active");
        this.hintToggle.classList.add("active");
        this._syncVoiceToggleUI();
        this._updateBackButton();
    }

    _onSend() {
        const text = this.userInput.value.trim();
        if (!text || this.isLoading) return;
        this.sendInput(text);
    }

    _onContinue() {
        if (this.isLoading) return;
        this.sendInput("(Weiter)");
    }

    // --- Back Button ---

    _onBack() {
        if (this.sceneHistoryIndex <= 0 || this.isLoading) return;
        this.sceneHistoryIndex--;
        const scene = this.sceneHistory[this.sceneHistoryIndex];
        this._renderScene(scene, { skipTypewriter: true });
        this._updateBackButton();
    }

    _updateBackButton() {
        this.backButton.disabled = this.sceneHistoryIndex <= 0;
    }

    // --- API Communication ---

    async sendInput(text) {
        if (this.isLoading) return;
        this._setLoading(true);
        this.userInput.value = "";

        // Hide scene-end choices and error hint when sending new input
        this._hideSceneEndChoices();
        this._hideErrorCorrection();

        try {
            const response = await Auth.fetchAuthenticated(`${CONFIG.API_BASE_URL}/generate_scene`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ user_input: text }),
            });

            if (!response.ok) {
                throw new Error(`Server-Fehler: ${response.status}`);
            }

            const sceneData = await response.json();

            // Push to local scene history
            this.sceneHistory.push(sceneData);
            this.sceneHistoryIndex = this.sceneHistory.length - 1;
            this._updateBackButton();

            // Cache affection, learning, time data from response
            if (sceneData.aoi_affection) this.lastAffection = sceneData.aoi_affection;
            if (sceneData.time) this.lastTime = sceneData.time;
            if (sceneData.learning) this.lastLearning = sceneData.learning;

            // Update HUD
            this._updateHUD(sceneData.time, sceneData.aoi_affection);

            // Render the scene
            await this._renderScene(sceneData);

            // Show error correction hint if present
            if (sceneData.analysis && sceneData.analysis.error_correction) {
                this._showErrorCorrection(sceneData.analysis.error_correction);
            }

            // Handle scene-end choices
            if (sceneData.scene_status && sceneData.scene_status.scene_end) {
                this._showSceneEndChoices(sceneData.scene_status.suggested_next || []);
            } else if (!sceneData.character) {
                // Narrator/transition scene: offer a simple continue button
                // instead of expecting free text input
                this._showNarratorContinue();
            }

        } catch (error) {
            this._showError(error.message);
        } finally {
            this._setLoading(false);
            this.userInput.focus();
        }
    }

    async _fetchStartPrompt() {
        this.startPrompt = "(Spielstart)";
        try {
            const response = await Auth.fetchAuthenticated(`${CONFIG.API_BASE_URL}/api/start_prompt`);
            if (response.ok) {
                const data = await response.json();
                if (data.prompt) {
                    this.startPrompt = data.prompt;
                    console.log("[VNEngine] Loaded start prompt from server.");
                }
            }
        } catch (e) {
            console.warn("[VNEngine] Could not fetch start prompt:", e);
        }
    }

    async _fetchAvailableAssets() {
        try {
            const response = await fetch(`${CONFIG.API_BASE_URL}/api/assets/available`);
            if (response.ok) {
                this.availableAssets = await response.json();
            }
        } catch (e) {
            console.warn("Could not fetch available assets:", e);
        }
    }

    // --- HUD ---

    _updateHUD(time, affection) {
        if (time) {
            this.hudDay.textContent = `Tag ${time.day || 1}`;
            const hour = time.hour != null ? time.hour : 14;
            this.hudHour.textContent = `${String(hour).padStart(2, "0")}:00`;
        }

        if (affection) {
            const tone = affection.tone || "neutral";
            const toneConfig = CONFIG.AFFECTION_TONES[tone] || CONFIG.AFFECTION_TONES.neutral;
            this.hudAffectionLabel.textContent = toneConfig.label;
            this.hudAffectionLabel.style.color = toneConfig.color;
            this.hudAffectionIcon.style.color = toneConfig.color;
        }
    }

    // --- Error Correction ---

    _showErrorCorrection(text) {
        if (!this.errorCorrectionHint || !text) return;
        this.errorCorrectionHint.textContent = text;
        // Only show if hints are enabled
        this.errorCorrectionHint.classList.toggle("hidden", !this.showHints);
    }

    _hideErrorCorrection() {
        if (!this.errorCorrectionHint) return;
        this.errorCorrectionHint.classList.add("hidden");
        this.errorCorrectionHint.textContent = "";
    }

    // --- Scene-End Choices ---

    _showSceneEndChoices(choices) {
        if (!this.sceneEndChoices || choices.length === 0) return;

        this.sceneEndChoices.innerHTML = "";

        for (const choice of choices) {
            const btn = document.createElement("button");
            btn.className = "scene-choice-button";
            // Format the choice label: replace underscores with spaces, capitalize
            btn.textContent = choice.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());
            btn.addEventListener("click", () => {
                this._hideSceneEndChoices();
                this.sendInput(`(Nächste Szene: ${choice})`);
            });
            this.sceneEndChoices.appendChild(btn);
        }

        this.sceneEndChoices.classList.remove("hidden");

        // Hide the regular input while choices are shown
        this.userInput.style.display = "none";
        this.sendButton.style.display = "none";
        this.continueButton.style.display = "none";
    }

    _hideSceneEndChoices() {
        if (!this.sceneEndChoices) return;
        this.sceneEndChoices.classList.add("hidden");
        this.sceneEndChoices.innerHTML = "";

        // Restore input area
        this.userInput.style.display = "";
        this.sendButton.style.display = "";
        this.continueButton.style.display = "";
    }

    _showNarratorContinue() {
        if (!this.sceneEndChoices) return;

        this.sceneEndChoices.innerHTML = "";

        const btn = document.createElement("button");
        btn.className = "scene-choice-button";
        btn.textContent = "Weiter ▸";
        btn.addEventListener("click", () => {
            this._hideSceneEndChoices();
            this.sendInput("(Weiter)");
        });
        this.sceneEndChoices.appendChild(btn);

        // Unlike scene-end choices, keep the text input available —
        // the player may still want to type something instead.
        this.sceneEndChoices.classList.remove("hidden");
    }

    // --- Scene Rendering ---

    async _renderScene(sceneData, { skipTypewriter = false } = {}) {
        this.currentScene = sceneData;

        // Translation defaults to hidden for every new text — revealing it
        // is a per-scene decision, not a sticky setting (learning aid).
        this._resetTranslation();

        if (sceneData.background) {
            await this._transitionBackground(sceneData.background);
        }

        await this._transitionCharacter(sceneData.character, sceneData.expression);
        this._updateCharacterName(sceneData.character);
        this._typewriteDialog(
            sceneData.dialog_jp,
            sceneData.dialog_jp_furigana || "",
            sceneData.dialog_de,
            skipTypewriter,
        );

        // Play TTS in parallel (non-blocking)
        if (sceneData.dialog_jp && !skipTypewriter) {
            this._playTTS(sceneData.dialog_jp, sceneData.expression);
        }
    }

    // --- Background ---

    async _transitionBackground(backgroundId) {
        const url = `${CONFIG.ASSET_PATHS.backgrounds}/${backgroundId}.png`;
        const loaded = await this._preloadImage(url);
        this.backgroundLayer.classList.add("fade-out");
        await this._wait(CONFIG.FADE_TRANSITION_MS);
        this.backgroundLayer.style.backgroundImage = `url('${url}')`;
        if (!loaded) {
            this.backgroundMissingLabel.textContent = `Missing: ${backgroundId}`;
            this.backgroundMissingLabel.classList.remove("hidden");
        } else {
            this.backgroundMissingLabel.classList.add("hidden");
        }
        this.backgroundLayer.classList.remove("fade-out");
    }

    // --- Character ---

    async _transitionCharacter(characterId, expression) {
        if (!characterId) {
            this.characterSprite.classList.add("hidden");
            this.characterMissingLabel.classList.add("hidden");
            return;
        }
        const expr = this._resolveExpression(characterId, expression);
        const url = `${CONFIG.ASSET_PATHS.characters}/${characterId}/${expr}.png`;
        const loaded = await this._preloadImage(url);
        this.characterSprite.classList.add("fade-out");
        await this._wait(CONFIG.FADE_TRANSITION_MS);
        this.characterSprite.src = url;
        this.characterSprite.alt = `${characterId} - ${expr}`;
        if (!loaded) {
            this.characterMissingLabel.textContent = `Missing: ${characterId}/${expr}`;
            this.characterMissingLabel.classList.remove("hidden");
        } else {
            this.characterMissingLabel.classList.add("hidden");
        }
        this.characterSprite.classList.remove("fade-out", "hidden");
    }

    _resolveExpression(characterId, expression) {
        if (!this.availableAssets || !this.availableAssets.characters) {
            return expression || CONFIG.DEFAULT_EXPRESSION;
        }
        const available = this.availableAssets.characters[characterId];
        if (!available) return expression || CONFIG.DEFAULT_EXPRESSION;
        if (available.includes(expression)) return expression;
        if (available.includes(CONFIG.DEFAULT_EXPRESSION)) return CONFIG.DEFAULT_EXPRESSION;
        return available[0] || CONFIG.DEFAULT_EXPRESSION;
    }

    // --- Dialog ---

    _typewriteDialog(dialogJp, dialogJpFurigana, dialogDe, skipTypewriter = false) {
        if (this.typewriterTimeout) {
            clearTimeout(this.typewriterTimeout);
            this.typewriterTimeout = null;
        }

        this.dialogText.innerHTML = "";
        this.translationText.textContent = dialogDe || "";

        if (!dialogJp) {
            this.dialogText.textContent = dialogDe || "";
            return;
        }

        const displayText = dialogJpFurigana || dialogJp;
        const rubyHtml = this._furiganaToRuby(displayText);

        if (skipTypewriter) {
            this.dialogText.innerHTML = rubyHtml;
            this._applyFuriganaVisibility();
            return;
        }

        const plainChars = dialogJp.split("");
        let index = 0;
        const type = () => {
            if (index < plainChars.length) {
                this.dialogText.textContent = dialogJp.substring(0, index + 1);
                index++;
                this.typewriterTimeout = setTimeout(type, CONFIG.TYPEWRITER_SPEED_MS);
            } else {
                this.dialogText.innerHTML = rubyHtml;
                this._applyFuriganaVisibility();
            }
        };
        type();
    }

    /**
     * Convert furigana notation to HTML <ruby> tags.
     * Format: 漢字[かんじ] — kanji (possibly with trailing kana) followed by [reading].
     * The match must START with a kanji character to avoid capturing preceding
     * hiragana particles (の, で, が, etc.) into the ruby group.
     */
    _furiganaToRuby(text) {
        if (!text) return "";
        // Normalize fullwidth brackets ［ ］ to halfwidth [ ]
        text = text.replace(/\uff3b/g, "[").replace(/\uff3d/g, "]");
        return text.replace(
            /([\u3005-\u3007\u3400-\u4DBF\u4E00-\u9FFF\u30F5\u30F6][\u3040-\u309F\u3005-\u3007\u3400-\u4DBF\u4E00-\u9FFF\u30F5\u30F6]*)\[([^\]]+)\]/g,
            '<ruby>$1<rt>$2</rt></ruby>'
        );
    }

    _applyFuriganaVisibility() {
        this.dialogText.classList.toggle("hide-furigana", !this.showFurigana);
    }

    // --- Toggle Buttons ---

    _toggleTranslation() {
        this.showTranslation = !this.showTranslation;
        this.translationText.classList.toggle("hidden", !this.showTranslation);
        this.translationToggle.classList.toggle("active", this.showTranslation);
    }

    _resetTranslation() {
        this.showTranslation = false;
        this.translationText.classList.add("hidden");
        this.translationToggle.classList.remove("active");
    }

    _toggleFurigana() {
        this.showFurigana = !this.showFurigana;
        this._applyFuriganaVisibility();
        this.furiganaToggle.classList.toggle("active", this.showFurigana);
    }

    _toggleHints() {
        this.showHints = !this.showHints;
        this.hintToggle.classList.toggle("active", this.showHints);
        // Immediately show/hide current hint
        if (this.errorCorrectionHint) {
            const hasContent = this.errorCorrectionHint.textContent.trim() !== "";
            this.errorCorrectionHint.classList.toggle("hidden", !this.showHints || !hasContent);
        }
    }

    // --- Voice / TTS ---

    _loadTTSPreference() {
        const stored = localStorage.getItem(CONFIG.TTS.LOCAL_STORAGE_KEY);
        if (stored !== null) return stored === "true";
        return CONFIG.TTS.ENABLED_BY_DEFAULT;
    }

    _saveTTSPreference() {
        localStorage.setItem(CONFIG.TTS.LOCAL_STORAGE_KEY, String(this.ttsEnabled));
    }

    _syncVoiceToggleUI() {
        const active = this.ttsEnabled && this.ttsAvailable;
        this.voiceToggle.classList.toggle("active", active);
        // Muted state hides the sound waves in the SVG icon (see CSS)
        this.voiceToggle.classList.toggle("muted", !active);
        // Show/hide replay button
        const showReplay = active && this._lastTTSText;
        this.voiceReplay.classList.toggle("hidden", !showReplay);
    }

    _toggleVoice() {
        this.ttsEnabled = !this.ttsEnabled;
        this._saveTTSPreference();
        this._syncVoiceToggleUI();
        // Stop any currently playing audio when turning off
        if (!this.ttsEnabled) {
            this._stopAudio();
        }
    }

    async _checkTTSAvailability() {
        try {
            const resp = await Auth.fetchAuthenticated(`${CONFIG.API_BASE_URL}/api/tts/status`);
            if (resp.ok) {
                const data = await resp.json();
                this.ttsAvailable = data.status === "ready";
                if (data.status === "loading") {
                    // Re-check after a delay
                    setTimeout(() => this._checkTTSAvailability(), 5000);
                }
                console.log(`[VNEngine] TTS status: ${data.status}`);
            }
        } catch (e) {
            console.warn("[VNEngine] TTS status check failed:", e);
            this.ttsAvailable = false;
        }
        this._syncVoiceToggleUI();
    }

    async _playTTS(text, expression) {
        if (!this.ttsEnabled || !this.ttsAvailable || !text) return;

        // Store for replay
        this._lastTTSText = text;
        this._lastTTSExpression = expression || "neutral";
        this._syncVoiceToggleUI();

        // Stop any previous audio
        this._stopAudio();

        // Strip furigana bracket annotations (e.g. 漢字[かんじ] → 漢字)
        // to prevent TTS from reading both the kanji and the reading.
        text = text.replace(/[\[\uff3b][^\]\uff3d]+[\]\uff3d]/g, "");

        // Truncate to first ~200 chars at a sentence boundary.
        if (text.length > 200) {
            const cut = text.substring(0, 200);
            const sepIdx = Math.max(
                cut.lastIndexOf("。"), cut.lastIndexOf("！"),
                cut.lastIndexOf("？"), cut.lastIndexOf("、"),
            );
            text = sepIdx > 0 ? cut.substring(0, sepIdx + 1) : cut;
        }

        try {
            const resp = await Auth.fetchAuthenticated(`${CONFIG.API_BASE_URL}/api/tts/generate`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ text, expression: expression || "neutral" }),
            });

            if (!resp.ok) {
                if (resp.status === 429) {
                    console.log("[VNEngine] TTS busy, skipping.");
                } else {
                    console.warn("[VNEngine] TTS generation failed:", resp.status);
                }
                return;
            }

            const arrayBuffer = await resp.arrayBuffer();
            if (arrayBuffer.byteLength === 0) {
                console.warn("[VNEngine] TTS returned empty audio.");
                return;
            }

            // Use Web Audio API — avoids CSP media-src restrictions on blob: URLs
            if (!this._audioContext) {
                this._audioContext = new (window.AudioContext || window.webkitAudioContext)();
            }
            if (this._audioContext.state === "suspended") {
                await this._audioContext.resume();
            }

            const audioBuffer = await this._audioContext.decodeAudioData(arrayBuffer);
            const source = this._audioContext.createBufferSource();
            source.buffer = audioBuffer;
            source.connect(this._audioContext.destination);

            source.addEventListener("ended", () => {
                if (this._currentSource === source) this._currentSource = null;
            });

            this._currentSource = source;
            source.start();
        } catch (e) {
            console.warn("[VNEngine] TTS playback failed:", e);
        }
    }

    _replayTTS() {
        if (this._lastTTSText) {
            this._playTTS(this._lastTTSText, this._lastTTSExpression);
        }
    }

    _stopAudio() {
        if (this._currentSource) {
            try {
                this._currentSource.stop();
            } catch (_) {
                // Already stopped — ignore
            }
            this._currentSource = null;
        }
    }

    _initKeyboardDetection() {
        const vv = window.visualViewport;
        if (!vv) return; // not supported (desktop browsers)

        const gameContainer = document.getElementById("game-container");
        const textboxLayer = document.getElementById("textbox-layer");
        let initialHeight = vv.height;

        const onResize = () => {
            // Keyboard is considered open when viewport shrinks by >150px
            const heightDiff = initialHeight - vv.height;
            const keyboardOpen = heightDiff > 150;

            gameContainer.classList.toggle("keyboard-open", keyboardOpen);

            if (keyboardOpen) {
                // Position textbox just above the keyboard
                const keyboardHeight = window.innerHeight - vv.height;
                textboxLayer.style.bottom = keyboardHeight + "px";
            } else {
                textboxLayer.style.bottom = "";
                initialHeight = vv.height;
            }
        };

        vv.addEventListener("resize", onResize);
    }

    // --- Character Name ---

    _updateCharacterName(characterId) {
        if (!characterId) {
            this.characterName.textContent = "";
            return;
        }
        this.characterName.textContent =
            CONFIG.CHARACTER_NAMES[characterId] || characterId;
    }

    // --- Menu System ---

    _openMenu() {
        this.menuOverlay.classList.remove("hidden");
        this.menuPlayerNameInput.value = this.playerName;
        this.menuPlayerNameStatus.textContent = "";
        this.menuScenarioStatus.textContent = "";
        this.adminRestartStatus.textContent = "";
        this.adminSection.classList.toggle("hidden", !this.isAdmin);
        this._refreshSaveSlots();
        this._loadScenario();
    }

    _closeMenu() {
        this.menuOverlay.classList.add("hidden");
    }

    async _refreshSaveSlots() {
        this.saveSlotsContainer.innerHTML = "";
        let existingSlots = {};

        try {
            const response = await Auth.fetchAuthenticated(`${CONFIG.API_BASE_URL}/api/save_slots`);
            if (response.ok) {
                const data = await response.json();
                for (const slot of data.slots) {
                    existingSlots[slot.slot_id] = slot;
                }
            }
        } catch (e) {
            console.warn("[VNEngine] Failed to load save slots:", e);
        }

        for (let i = 1; i <= CONFIG.MAX_SAVE_SLOTS; i++) {
            const slotEl = this._createSlotElement(i, existingSlots[i] || null);
            this.saveSlotsContainer.appendChild(slotEl);
        }
    }

    _createSlotElement(slotId, slotData) {
        const el = document.createElement("div");
        el.className = "save-slot";

        const num = document.createElement("div");
        num.className = "slot-number";
        num.textContent = slotId;
        el.appendChild(num);

        const info = document.createElement("div");
        info.className = "slot-info";

        if (slotData) {
            const name = document.createElement("div");
            name.className = "slot-name";
            name.textContent = slotData.name || `Spielstand ${slotId}`;
            info.appendChild(name);

            const details = document.createElement("div");
            details.className = "slot-details";
            const date = new Date(slotData.saved_at).toLocaleString("de-DE");
            details.textContent = `Tag ${slotData.day_number} · ${slotData.turn_count} Züge · ${date}`;
            info.appendChild(details);
        } else {
            const empty = document.createElement("div");
            empty.className = "slot-empty";
            empty.textContent = "— Leer —";
            info.appendChild(empty);
        }
        el.appendChild(info);

        const actions = document.createElement("div");
        actions.className = "slot-actions";

        // Save button (always shown)
        const saveBtn = document.createElement("button");
        saveBtn.textContent = "Speichern";
        saveBtn.addEventListener("click", () => this._saveToSlot(slotId));
        actions.appendChild(saveBtn);

        if (slotData) {
            // Load button
            const loadBtn = document.createElement("button");
            loadBtn.className = "load-btn";
            loadBtn.textContent = "Laden";
            loadBtn.addEventListener("click", () => this._loadFromSlot(slotId));
            actions.appendChild(loadBtn);
        }

        el.appendChild(actions);
        return el;
    }

    async _saveToSlot(slotId) {
        try {
            const response = await Auth.fetchAuthenticated(`${CONFIG.API_BASE_URL}/api/save_slots/${slotId}`, {
                method: "POST",
                headers: { "Content-Type": "application/json" },
                body: JSON.stringify({ name: "" }),
            });
            if (!response.ok) throw new Error(`Save failed: ${response.status}`);
            console.log(`[VNEngine] Saved to slot ${slotId}`);
            await this._refreshSaveSlots();
        } catch (e) {
            console.error("[VNEngine] Save failed:", e);
        }
    }

    async _loadFromSlot(slotId) {
        try {
            const response = await Auth.fetchAuthenticated(`${CONFIG.API_BASE_URL}/api/save_slots/${slotId}/load`, {
                method: "POST",
            });
            if (!response.ok) {
                this._showError("Spielstand konnte nicht geladen werden.");
                return;
            }
            const state = await response.json();
            console.log(`[VNEngine] Loaded slot ${slotId}`);

            // Clear stale frontend state before rendering loaded state
            this.dialogText.innerHTML = "";
            this.translationText.textContent = "";
            this.characterName.textContent = "";
            this.characterSprite.classList.add("hidden");
            this.characterMissingLabel.classList.add("hidden");
            this.backgroundMissingLabel.classList.add("hidden");
            this._hideErrorCorrection();
            this._hideSceneEndChoices();
            this._closeMenu();

            // Reload scene history from backend
            await this._loadSceneHistory();
            this._updateBackButton();

            // Update HUD and cached state from the load response directly
            if (state.affection) this.lastAffection = state.affection;
            if (state.learning) this.lastLearning = state.learning;
            if (state.time) this.lastTime = state.time;
            this._updateHUD(state.time, state.affection);

            if (state.last_scene) {
                await this._renderScene(state.last_scene, { skipTypewriter: true });
                if (!state.last_scene.character) this._showNarratorContinue();
            }
        } catch (e) {
            console.error("[VNEngine] Load failed:", e);
            this._showError("Spielstand konnte nicht geladen werden.");
        }
    }

    async _refreshGameState() {
        try {
            const response = await Auth.fetchAuthenticated(`${CONFIG.API_BASE_URL}/game_state`);
            if (response.ok) {
                const state = await response.json();
                if (state.affection) this.lastAffection = state.affection;
                if (state.learning) this.lastLearning = state.learning;
                if (state.time) this.lastTime = state.time;
                this._updateHUD(state.time, state.affection);
            }
        } catch (e) {
            console.warn("[VNEngine] Could not refresh game state:", e);
        }
    }

    async _onNewGame() {
        if (!confirm("Neues Spiel starten? Der aktuelle Fortschritt geht verloren, wenn er nicht gespeichert wurde.")) {
            return;
        }

        try {
            const resp = await Auth.fetchAuthenticated(`${CONFIG.API_BASE_URL}/game_state/reset`, { method: "POST" });
            if (!resp.ok) {
                this._showError("Spiel konnte nicht zurückgesetzt werden.");
                return;
            }
            const freshState = await resp.json();
            if (freshState.time) this.lastTime = freshState.time;
            if (freshState.affection) this.lastAffection = freshState.affection;
            if (freshState.learning) this.lastLearning = freshState.learning;
            this._updateHUD(freshState.time, freshState.affection);
        } catch (e) {
            console.warn("[VNEngine] Reset request failed:", e);
            this._showError("Spiel konnte nicht zurückgesetzt werden.");
            return;
        }

        this.sceneHistory = [];
        this.sceneHistoryIndex = -1;
        this._updateBackButton();
        this._closeMenu();

        // Clear any stale loading state before starting fresh
        this._setLoading(false);
        this.dialogText.innerHTML = "";
        this.translationText.textContent = "";
        this.characterName.textContent = "";
        this.characterSprite.classList.add("hidden");
        this.characterMissingLabel.classList.add("hidden");
        this.backgroundMissingLabel.classList.add("hidden");
        this._hideErrorCorrection();
        this._hideSceneEndChoices();

        // Re-fetch start prompt in case the scenario was changed
        await this._fetchStartPrompt();

        await this.sendInput(this.startPrompt);
    }

    // --- History Panel ---

    _openHistory() {
        this.historyOverlay.classList.remove("hidden");
        this._renderHistoryEntries();
    }

    _closeHistory() {
        this.historyOverlay.classList.add("hidden");
    }

    _renderHistoryEntries() {
        this.historyEntries.innerHTML = "";

        if (this.sceneHistory.length === 0) {
            const empty = document.createElement("div");
            empty.className = "slot-empty";
            empty.style.textAlign = "center";
            empty.style.padding = "20px";
            empty.textContent = "Noch kein Verlauf vorhanden.";
            this.historyEntries.appendChild(empty);
            return;
        }

        for (const scene of this.sceneHistory) {
            const entry = document.createElement("div");
            entry.className = "history-entry";

            const isNarrator = !scene.character;
            if (isNarrator) entry.classList.add("narrator");

            // Character name
            const charName = document.createElement("div");
            charName.className = "history-char-name";
            if (isNarrator) {
                charName.textContent = "Erzähler";
            } else {
                charName.textContent = CONFIG.CHARACTER_NAMES[scene.character] || scene.character;
            }
            entry.appendChild(charName);

            // Japanese dialog (with furigana)
            if (scene.dialog_jp) {
                const jp = document.createElement("div");
                jp.className = "history-dialog-jp";
                const furiganaText = scene.dialog_jp_furigana || scene.dialog_jp;
                jp.innerHTML = this._furiganaToRuby(furiganaText);
                entry.appendChild(jp);
            }

            // German translation
            if (scene.dialog_de) {
                const de = document.createElement("div");
                de.className = "history-dialog-de";
                de.textContent = scene.dialog_de;
                entry.appendChild(de);
            }

            this.historyEntries.appendChild(entry);
        }

        // Scroll to bottom (latest entry)
        this.historyEntries.scrollTop = this.historyEntries.scrollHeight;
    }

    // --- Stats Panel ---

    _openStats() {
        this.statsOverlay.classList.remove("hidden");
        this._renderStats();
    }

    _closeStats() {
        this.statsOverlay.classList.add("hidden");
    }

    _renderStats() {
        this._renderAffectionStats();
        this._renderLearningStats();
    }

    _renderAffectionStats() {
        const section = this.statsAffectionSection;
        section.innerHTML = "<h3>Zuneigung</h3>";

        const affection = this.lastAffection;
        if (!affection) {
            const msg = document.createElement("div");
            msg.className = "stats-empty-message";
            msg.textContent = "Noch keine Daten vorhanden.";
            section.appendChild(msg);
            return;
        }

        // Tone display
        const tone = affection.tone || "neutral";
        const toneConfig = CONFIG.AFFECTION_TONES[tone] || CONFIG.AFFECTION_TONES.neutral;
        const score = affection.weighted_score != null ? affection.weighted_score : 20;

        const toneDisplay = document.createElement("div");
        toneDisplay.className = "stats-tone-display";
        toneDisplay.innerHTML = `
            <span class="stats-tone-icon" style="color: ${toneConfig.color}">&#9829;</span>
            <div class="stats-tone-info">
                <div class="stats-tone-label" style="color: ${toneConfig.color}">${toneConfig.label}</div>
                <div class="stats-tone-score">Score: ${score.toFixed(1)} / 100</div>
            </div>
        `;
        section.appendChild(toneDisplay);

        // Factor bars
        const factors = [
            { key: "language_effort", label: "Sprachbemühung", weight: "35%" },
            { key: "cultural_interest", label: "Kulturinteresse", weight: "25%" },
            { key: "personal_bond", label: "Pers. Bindung", weight: "20%" },
            { key: "humor", label: "Humor", weight: "10%" },
            { key: "reliability", label: "Zuverlässigkeit", weight: "10%" },
        ];

        for (const factor of factors) {
            const value = affection[factor.key] != null ? affection[factor.key] : 20;
            const pct = Math.min(100, Math.max(0, value));

            const row = document.createElement("div");
            row.className = "stats-factor";
            row.innerHTML = `
                <span class="stats-factor-name">${factor.label} (${factor.weight})</span>
                <div class="stats-factor-bar">
                    <div class="stats-factor-fill" style="width: ${pct}%; background: ${toneConfig.color}"></div>
                </div>
                <span class="stats-factor-value">${pct.toFixed(0)}</span>
            `;
            section.appendChild(row);
        }
    }

    _renderLearningStats() {
        const section = this.statsLearningSection;
        section.innerHTML = "<h3>Grammatik-Fortschritt</h3>";

        const learning = this.lastLearning;
        if (!learning) {
            const msg = document.createElement("div");
            msg.className = "stats-empty-message";
            msg.textContent = "Noch keine Daten vorhanden.";
            section.appendChild(msg);
            return;
        }

        // Overall level badge
        const level = learning.overall_level || "N5";
        const badge = document.createElement("div");
        badge.className = "stats-level-badge";
        badge.textContent = `Level: ${level}`;
        section.appendChild(badge);

        // Topics
        const topics = learning.topics || {};
        const topicEntries = Object.entries(topics);

        if (topicEntries.length === 0) {
            const msg = document.createElement("div");
            msg.className = "stats-empty-message";
            msg.textContent = "Noch keine Grammatik-Themen geübt.";
            section.appendChild(msg);
            this._renderVocabStats(section, learning);
            return;
        }

        // Sort by mastery (lowest first to show weak points at top)
        topicEntries.sort((a, b) => (a[1].mastery || 0) - (b[1].mastery || 0));

        for (const [topicId, topicData] of topicEntries) {
            const mastery = Math.min(1, Math.max(0, topicData.mastery || 0));
            const pct = (mastery * 100).toFixed(0);
            const label = topicId.replace(/_/g, " ").replace(/\b\w/g, c => c.toUpperCase());

            const row = document.createElement("div");
            row.className = "stats-topic";

            const nameSpan = document.createElement("span");
            nameSpan.className = "stats-topic-name";
            nameSpan.title = topicId;
            nameSpan.textContent = label;
            row.appendChild(nameSpan);

            const barDiv = document.createElement("div");
            barDiv.className = "stats-topic-bar";
            const fillDiv = document.createElement("div");
            fillDiv.className = "stats-topic-fill";
            fillDiv.style.width = `${pct}%`;
            barDiv.appendChild(fillDiv);
            row.appendChild(barDiv);

            const valueSpan = document.createElement("span");
            valueSpan.className = "stats-topic-value";
            valueSpan.textContent = `${pct}%`;
            row.appendChild(valueSpan);

            section.appendChild(row);
        }

        this._renderVocabStats(section, learning);
    }

    _renderVocabStats(section, learning) {
        const vocab = (learning && learning.vocab) || {};
        const entries = Object.values(vocab);

        const heading = document.createElement("h3");
        heading.textContent = `Vokabelheft (${entries.length})`;
        heading.style.marginTop = "1em";
        section.appendChild(heading);

        if (entries.length === 0) {
            const msg = document.createElement("div");
            msg.className = "stats-empty-message";
            msg.textContent = "Noch keine Vokabeln gesammelt.";
            section.appendChild(msg);
            return;
        }

        // Weakest words first (they are due for review), max 25 shown
        entries.sort((a, b) => (a.strength || 0) - (b.strength || 0));

        for (const v of entries.slice(0, 25)) {
            const strength = Math.min(1, Math.max(0, v.strength || 0));
            const pct = (strength * 100).toFixed(0);

            const row = document.createElement("div");
            row.className = "stats-topic";

            const nameSpan = document.createElement("span");
            nameSpan.className = "stats-topic-name";
            nameSpan.title = v.meaning_de || "";
            nameSpan.textContent = v.reading ? `${v.word}（${v.reading}）` : v.word;
            row.appendChild(nameSpan);

            const meaningSpan = document.createElement("span");
            meaningSpan.className = "stats-topic-name";
            meaningSpan.style.opacity = "0.75";
            meaningSpan.textContent = v.meaning_de || "";
            row.appendChild(meaningSpan);

            const barDiv = document.createElement("div");
            barDiv.className = "stats-topic-bar";
            const fillDiv = document.createElement("div");
            fillDiv.className = "stats-topic-fill";
            fillDiv.style.width = `${pct}%`;
            barDiv.appendChild(fillDiv);
            row.appendChild(barDiv);

            section.appendChild(row);
        }

        if (entries.length > 25) {
            const more = document.createElement("div");
            more.className = "stats-empty-message";
            more.textContent = `… und ${entries.length - 25} weitere`;
            section.appendChild(more);
        }
    }

    // --- Utility ---

    _preloadImage(url) {
        if (this.assetCache.has(url)) return Promise.resolve(true);
        return new Promise((resolve) => {
            const img = new Image();
            img.onload = () => {
                this.assetCache.set(url, true);
                resolve(true);
            };
            img.onerror = () => {
                console.warn("Failed to load asset:", url);
                resolve(false);
            };
            img.src = url;
        });
    }

    _wait(ms) {
        return new Promise((resolve) => setTimeout(resolve, ms));
    }

    _setLoading(loading) {
        this.isLoading = loading;
        this.loadingOverlay.classList.toggle("hidden", !loading);
        this.sendButton.disabled = loading;
        this.continueButton.disabled = loading;
        this.userInput.disabled = loading;
    }

    _showError(message) {
        this.dialogText.textContent = `[Fehler: ${message}]`;
        this.translationText.textContent = "";
        this.characterName.textContent = "";
    }
}

// --- Bootstrap ---
document.addEventListener("DOMContentLoaded", () => {
    window.vnEngine = new VNEngine();
});
