/**
 * Auth helper — manages JWT token storage and authenticated API calls.
 */
const Auth = {
    TOKEN_KEY: "japan_rpg_token",
    USERNAME_KEY: "japan_rpg_username",

    getToken() {
        return localStorage.getItem(this.TOKEN_KEY);
    },

    getUsername() {
        return localStorage.getItem(this.USERNAME_KEY);
    },

    setAuth(token, username) {
        localStorage.setItem(this.TOKEN_KEY, token);
        localStorage.setItem(this.USERNAME_KEY, username);
    },

    clearAuth() {
        localStorage.removeItem(this.TOKEN_KEY);
        localStorage.removeItem(this.USERNAME_KEY);
    },

    isLoggedIn() {
        return !!this.getToken();
    },

    /**
     * Wrapper around fetch() that adds the Authorization header
     * and redirects to login on 401.
     */
    async fetchAuthenticated(url, options = {}) {
        const token = this.getToken();
        if (!token) {
            this.redirectToLogin();
            throw new Error("Not authenticated");
        }

        const headers = { ...(options.headers || {}) };
        headers["Authorization"] = `Bearer ${token}`;

        const response = await fetch(url, { ...options, headers });

        if (response.status === 401) {
            this.clearAuth();
            this.redirectToLogin();
            throw new Error("Session expired");
        }

        return response;
    },

    redirectToLogin() {
        window.location.href = "/app/login.html";
    },

    logout() {
        this.clearAuth();
        this.redirectToLogin();
    },
};
