// RIS - Reliable Internet Services
// Shared application functions

function getData(key, defaultValue = []) {
    try {
        const data = localStorage.getItem(key);

        if (!data) {
            return defaultValue;
        }

        return JSON.parse(data);
    } catch (error) {
        console.error("RIS storage error:", error);
        return defaultValue;
    }
}

function saveData(key, data) {
    localStorage.setItem(key, JSON.stringify(data));
}

function generateId(prefix = "RIS") {
    const time = Date.now().toString().slice(-7);
    const random = Math.floor(Math.random() * 900 + 100);

    return `${prefix}-${time}${random}`;
}

function formatCurrency(amount) {
    return "UGX " + Number(amount || 0).toLocaleString();
}

function formatDate(date) {
    if (!date) return "-";

    const d = new Date(date);

    if (isNaN(d.getTime())) return date;

    return d.toLocaleDateString("en-GB");
}

function todayString() {
    const date = new Date();

    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");

    return `${year}-${month}-${day}`;
}

function addDays(dateString, days) {
    const date = new Date(dateString);

    date.setDate(date.getDate() + Number(days));

    const year = date.getFullYear();
    const month = String(date.getMonth() + 1).padStart(2, "0");
    const day = String(date.getDate()).padStart(2, "0");

    return `${year}-${month}-${day}`;
}

function showMessage(elementId, message, type = "success") {
    const element = document.getElementById(elementId);

    if (!element) return;

    element.className = `alert alert-${type}`;
    element.textContent = message;
    element.style.display = "block";

    setTimeout(() => {
        element.style.display = "none";
    }, 4000);
}

function confirmDelete(message = "Are you sure you want to delete this item?") {
    return window.confirm(message);
}

function getPackageById(id) {
    const packages = getData("RIS_packages", []);

    return packages.find(pkg => pkg.id === id);
}

function getCustomerById(id) {
    const customers = getData("RIS_customers", []);

    return customers.find(customer => customer.id === id);
}

function getActivePackages() {
    return getData("RIS_packages", []).filter(
        pkg => pkg.status === "Active"
    );
}

function updateExpiredCustomers() {
    const customers = getData("RIS_customers", []);
    const today = new Date(todayString());

    let changed = false;

    customers.forEach(customer => {
        if (!customer.expiryDate) return;

        const expiry = new Date(customer.expiryDate);

        if (
            expiry < today &&
            customer.status === "Active"
        ) {
            customer.status = "Expired";
            changed = true;
        }
    });

    if (changed) {
        saveData("RIS_customers", customers);
    }
}

function updateExpiredVouchers() {
    const vouchers = getData("RIS_vouchers", []);
    const today = new Date(todayString());

    let changed = false;

    vouchers.forEach(voucher => {
        if (!voucher.expiryDate) return;

        const expiry = new Date(voucher.expiryDate);

        if (
            expiry < today &&
            voucher.status === "Unused"
        ) {
            voucher.status = "Expired";
            changed = true;
        }
    });

    if (changed) {
        saveData("RIS_vouchers", vouchers);
    }
}

function initializePackages() {
    const existing = getData("RIS_packages", null);

    if (existing !== null) {
        return;
    }

    const packages = [
        {
            id: generateId("PKG"),
            name: "Basic",
            speed: 5,
            unit: "Mbps",
            price: 30000,
            validity: "30 Days",
            status: "Active",
            createdAt: new Date().toISOString()
        },
        {
            id: generateId("PKG"),
            name: "Standard",
            speed: 10,
            unit: "Mbps",
            price: 50000,
            validity: "30 Days",
            status: "Active",
            createdAt: new Date().toISOString()
        },
        {
            id: generateId("PKG"),
            name: "Premium",
            speed: 20,
            unit: "Mbps",
            price: 80000,
            validity: "30 Days",
            status: "Active",
            createdAt: new Date().toISOString()
        },
        {
            id: generateId("PKG"),
            name: "Business",
            speed: 50,
            unit: "Mbps",
            price: 150000,
            validity: "30 Days",
            status: "Active",
            createdAt: new Date().toISOString()
        }
    ];

    saveData("RIS_packages", packages);
}

function initializeApp() {
    initializePackages();
    updateExpiredCustomers();
    updateExpiredVouchers();
}

initializeApp();