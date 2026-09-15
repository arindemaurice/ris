/* =========================================================
   RIS - SECURITY SYSTEM
   Step 11
========================================================= */

const RIS_SECURITY_CONFIG = {
    adminSessionKey: "RIS_admin_session",
    customerSessionKey: "RIS_customer_session",

    // Session lifetime: 30 minutes
    sessionTimeout: 30 * 60 * 1000
};


/* =========================================================
   SESSION TIME
========================================================= */

function updateSessionActivity(sessionKey) {
    const session = localStorage.getItem(sessionKey);

    if (!session) {
        return;
    }

    try {
        const data = JSON.parse(session);

        data.lastActivity = Date.now();

        localStorage.setItem(sessionKey, JSON.stringify(data));
    } catch (error) {
        console.error("Session update error:", error);
    }
}


/* =========================================================
   CHECK SESSION EXPIRY
========================================================= */

function isSessionExpired(sessionKey) {
    const session = localStorage.getItem(sessionKey);

    if (!session) {
        return true;
    }

    try {
        const data = JSON.parse(session);

        if (!data.lastActivity) {
            return false;
        }

        const inactiveTime = Date.now() - data.lastActivity;

        return inactiveTime > RIS_SECURITY_CONFIG.sessionTimeout;

    } catch (error) {
        console.error("Session check error:", error);

        return true;
    }
}


/* =========================================================
   ADMIN SECURITY
========================================================= */

function secureAdminPage() {

    const sessionKey = RIS_SECURITY_CONFIG.adminSessionKey;

    if (!localStorage.getItem(sessionKey)) {
        window.location.href = "admin-login.html";
        return;
    }

    if (isSessionExpired(sessionKey)) {

        localStorage.removeItem(sessionKey);

        alert("Your admin session has expired. Please log in again.");

        window.location.href = "admin-login.html";

        return;
    }

    updateSessionActivity(sessionKey);
}


/* =========================================================
   CUSTOMER SECURITY
========================================================= */

function secureCustomerPage() {

    const sessionKey = RIS_SECURITY_CONFIG.customerSessionKey;

    if (!localStorage.getItem(sessionKey)) {
        window.location.href = "customer-login.html";
        return;
    }

    if (isSessionExpired(sessionKey)) {

        localStorage.removeItem(sessionKey);

        alert("Your customer session has expired. Please log in again.");

        window.location.href = "customer-login.html";

        return;
    }

    updateSessionActivity(sessionKey);
}


/* =========================================================
   ADMIN LOGOUT
========================================================= */

function secureAdminLogout() {

    localStorage.removeItem(
        RIS_SECURITY_CONFIG.adminSessionKey
    );

    window.location.href = "admin-login.html";
}


/* =========================================================
   CUSTOMER LOGOUT
========================================================= */

function secureCustomerLogout() {

    localStorage.removeItem(
        RIS_SECURITY_CONFIG.customerSessionKey
    );

    window.location.href = "customer-login.html";
}


/* =========================================================
   CLEAR BOTH SESSIONS
========================================================= */

function clearAllSessions() {

    localStorage.removeItem(
        RIS_SECURITY_CONFIG.adminSessionKey
    );

    localStorage.removeItem(
        RIS_SECURITY_CONFIG.customerSessionKey
    );
}


/* =========================================================
   AUTOMATIC SESSION CHECK
========================================================= */

function startSecurityMonitor(type) {

    const sessionKey =
        type === "admin"
            ? RIS_SECURITY_CONFIG.adminSessionKey
            : RIS_SECURITY_CONFIG.customerSessionKey;

    setInterval(function () {

        if (!localStorage.getItem(sessionKey)) {
            return;
        }

        if (isSessionExpired(sessionKey)) {

            localStorage.removeItem(sessionKey);

            alert(
                "Your session has expired because of inactivity."
            );

            if (type === "admin") {
                window.location.href = "admin-login.html";
            } else {
                window.location.href = "customer-login.html";
            }
        }

    }, 60 * 1000);
}


/* =========================================================
   USER ACTIVITY TRACKING
========================================================= */

function startActivityTracking(type) {

    const sessionKey =
        type === "admin"
            ? RIS_SECURITY_CONFIG.adminSessionKey
            : RIS_SECURITY_CONFIG.customerSessionKey;

    const events = [
        "click",
        "mousemove",
        "keydown",
        "scroll",
        "touchstart"
    ];

    events.forEach(function(eventName) {

        document.addEventListener(eventName, function() {

            if (localStorage.getItem(sessionKey)) {
                updateSessionActivity(sessionKey);
            }

        });

    });
}


/* =========================================================
   INPUT CLEANING
========================================================= */

function cleanInput(value) {

    if (typeof value !== "string") {
        return "";
    }

    return value
        .trim()
        .replace(/[<>]/g, "");
}


/* =========================================================
   PHONE VALIDATION
========================================================= */

function isValidPhone(phone) {

    if (!phone) {
        return false;
    }

    const cleaned = phone.replace(/[\s\-()]/g, "");

    return /^(\+256|0)[0-9]{9}$/.test(cleaned);
}


/* =========================================================
   EMAIL VALIDATION
========================================================= */

function isValidEmail(email) {

    if (!email) {
        return true;
    }

    return /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email);
}


/* =========================================================
   PASSWORD VALIDATION
========================================================= */

function isStrongPassword(password) {

    if (!password) {
        return false;
    }

    return (
        password.length >= 6
    );
}


/* =========================================================
   INITIALIZE SECURITY
========================================================= */

document.addEventListener("DOMContentLoaded", function() {

    console.log("RIS Security System loaded.");

});