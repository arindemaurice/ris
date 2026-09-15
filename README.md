# RIS — Reliable Internet Services

## Project Overview

RIS (Reliable Internet Services) is an Internet Service Provider management and billing system designed to help manage customers, internet packages, vouchers, payments, and internet access.

The system is being developed to provide a simple and reliable way for an ISP to manage its customers and internet services.

## Main Features

* Customer registration and management
* Customer login and portal
* Automatic customer registration
* Customer information stored in a database
* Internet package management
* Voucher generation and management
* Payment management
* Flutterwave payment integration
* Payment verification
* Customer payment history
* Router and MikroTik management
* Internet usage tracking
* Reports and statistics
* Admin dashboard
* Customer account and service status management

## Customer Registration

When a new customer visits the RIS system, a registration popup can be displayed.

The customer provides information such as:

* Full name
* Phone number
* Email address
* Username
* Password
* Internet package

After registration, the information is automatically submitted to the RIS backend and stored in the customer database.

## Payment System

RIS integrates with Flutterwave to allow customers to make internet service payments.

The payment process is:

1. Customer selects an amount or package.
2. RIS creates a payment request.
3. Customer is redirected to Flutterwave.
4. Customer completes the payment.
5. RIS receives the payment result.
6. RIS verifies the transaction.
7. The customer's account can then be updated.

## Internet Access Control

RIS is designed to work with routers and MikroTik equipment to control customer internet access.

The system can be used to:

* Activate customer internet access.
* Disable expired accounts.
* Apply internet packages.
* Track customer usage.
* Apply data limits.
* Control customer access according to their account status.

## Technology Used

### Frontend

* HTML
* CSS
* JavaScript

### Backend

* Python
* Flask
* Flask-CORS

### Database

* SQLite / relational database

### Payment Gateway

* Flutterwave

### Network Management

* MikroTik / Router integration

## Project Structure

```text
RIS
│
├── backend
│   ├── app.py
│   ├── requirements.txt
│   └── .env
│
├── css
│
├── js
│
├── pages
│   ├── customer-login.html
│   ├── customer-portal.html
│   ├── payment.html
│   ├── payment-result.html
│   ├── customers.html
│   ├── packages.html
│   ├── vouchers.html
│   ├── payments.html
│   ├── routers.html
│   └── reports.html
│
├── index.html
└── README.md
```

## Running the Project

Start the backend from the backend directory:

```powershell
cd "C:\Users\VU-STUDENT\Desktop\ris\backend"
python app.py
```

The RIS backend runs locally on:

```text
http://127.0.0.1:5000
```

The website can be accessed through:

```text
http://localhost:5000/site/index.html
```

## Development Status

RIS is currently under active development.

Completed components include:

* Admin dashboard
* Customer management
* Internet packages
* Vouchers
* Payments
* Customer portal
* Flutterwave payment integration
* Payment verification
* Payment result page
* Router management
* Usage tracking
* Reports

Current development focus:

* Automatic customer registration
* Database storage
* Automatic package activation
* Internet access control
* MikroTik integration
* Automatic data/usage management

## Security

Sensitive credentials such as payment gateway secret keys must be stored in environment variables and must never be placed directly in frontend code or publicly shared.

## Project Goal

The goal of RIS is to provide a reliable ISP management platform that connects customer registration, billing, payments, internet packages, usage tracking, and network access into one system.

