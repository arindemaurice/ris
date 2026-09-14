// RIS ADMIN AUTHENTICATION

const RIS_ADMIN_SESSION = "RIS_admin_session";

function isAdminLoggedIn() {
    return localStorage.getItem(RIS_ADMIN_SESSION) !== null;
}

function requireAdminLogin() {

    if (!isAdminLoggedIn()) {
        window.location.href = "admin-login.html";
    }

}

function getAdminSession() {

    const session = localStorage.getItem(RIS_ADMIN_SESSION);

    if (!session) {
        return null;
    }

    try {
        return JSON.parse(session);
    } catch (error) {
        return null;
    }

}

function adminLogout() {

    localStorage.removeItem(RIS_ADMIN_SESSION);

    window.location.href = "admin-login.html";

}