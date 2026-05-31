/**
 * Shared frontend helpers (loaded as a global before engine.js).
 *
 * Exposes: escapeHtml, furiganaToRuby, createEl, notify.
 */

/** Escape the five HTML-significant characters so text can't inject markup. */
function escapeHtml(text) {
    if (text == null) return "";
    return String(text)
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
}

/**
 * Convert furigana notation to HTML <ruby> tags.
 * Format: 漢字[かんじ] — kanji (possibly with trailing kana) followed by [reading].
 *
 * SECURITY: the input is AI-generated and could contain injected markup
 * (e.g. via prompt injection). We HTML-escape FIRST, then build the ruby tags
 * ourselves, so any injected <script>/<img> is rendered inert while the
 * furigana brackets (which escaping leaves untouched) still work.
 */
function furiganaToRuby(text) {
    if (!text) return "";
    // Normalize fullwidth brackets to halfwidth before escaping.
    text = text.replace(/［/g, "[").replace(/］/g, "]");
    text = escapeHtml(text);
    return text.replace(
        /([々-〇㐀-䶿一-鿿ヵヶ][぀-ゟ々-〇㐀-䶿一-鿿ヵヶ]*)\[([^\]]+)\]/g,
        "<ruby>$1<rt>$2</rt></ruby>"
    );
}

/** Create an element with an optional class and text content. */
function createEl(tag, className, text) {
    const el = document.createElement(tag);
    if (className) el.className = className;
    if (text != null) el.textContent = text;
    return el;
}

/**
 * Show a transient, non-blocking notification banner.
 * kind: "info" | "warning" | "error".
 */
function notify(message, kind = "info") {
    const host = document.getElementById("notification");
    if (!host) return;
    host.textContent = message;
    host.className = `notification ${kind}`;
    host.classList.remove("hidden");
    clearTimeout(notify._timer);
    notify._timer = setTimeout(() => host.classList.add("hidden"), 4000);
}
