# GPUShare — A Self‑Hosted GPU Marketplace

i created this **GPUShare** and [`gpushare`](https://pypi.org/project/gpushare) library from the ground up because I was tired of watching my expensive GPUs collect dust.  Friends kept asking to borrow compute time for their machine‑learning experiments, and I wanted a secure, transparent way to share resources without handing over SSH keys or opening firewall holes.  This project evolved into a self‑hosted platform where people can offer spare GPUs to a trusted community, request access when they need compute, and manage everything through a friendly web interface and API.

This document is intentionally long and chatty.  It mixes a personal narrative with technical detail so you can follow my thought process while also learning how to set up, run and extend GPUShare yourself.

And Yes, I have used chatGPT to rewrite some of this ReadME file.

---

## Contents

1. [What Is GPUShare?](#what-is-gpushare)
2. [Why I Built It](#why-i-built-it)
3. [Feature Overview](#feature-overview)
4. [Architecture and Technology Stack](#architecture-and-technology-stack)
5. [Installation and Configuration](#installation-and-configuration)
6. [Running the Server](#running-the-server)
7. [User Roles and Workflows](#user-roles-and-workflows)
8. [Using the Web Interface](#using-the-web-interface)
9. [Running the GPU Host Agent](#running-the-gpu-host-agent)
10. [The Python Client Library](#the-python-client-library)
11. [Extending and Customising GPUShare](#extending-and-customising-gpushare)
12. [Troubleshooting and FAQ](#troubleshooting-and-faq)

---

## What Is GPUShare?

At its core, **GPUShare** is a self‑hosted platform that lets you:

- **Host your own GPUs** so other users in your community can request access to them.  Each GPU you host can be monitored, taken offline, set to idle or back to busy, and its usage history is recorded.
- **Browse and request GPUs** hosted by others.  If you need a few hours of compute for a deep‑learning model or some heavy linear algebra, you can look through available cards, choose one that fits your needs and submit a request.
- **Moderate and manage access** via role‑based permissions.  Moderators approve or deny access requests, admins manage users and GPUs, and a special superadmin arbitrates actions between admins.
- **Automate everything** via API tokens and a JSON API.  Tokens let you authenticate programmatically without going through the OTP flow every time, which is perfect for command‑line scripts and CI workflows.

The entire platform runs on your own hardware or VPS.  No cloud vendor lock‑in, no hidden compute fees, just you and your GPUs.

## Why I Built It

I’m a Computer Science student with decent hardware and Very Good Low level knowledge.  I have powerful GPUs that I use for side projects.  When I’m not crunching numbers, those cards sit idle.  Meanwhile, friends working on Kaggle competitions or training models were always on the hunt for more compute.  Public cloud solutions exist, but they’re expensive and overkill for many small experiments.

So I thought: **lets try building very small tunnel that allows user to connect to gpu compute and execute code from anywhere**. from that very simple script. the entire wrapping of this project born. Something where I control who gets access, when they get it, and under what conditions.  Security was paramount no one wants to open a full SSH session to a stranger.  I wanted OTP‑based login, per‑request approvals, and the ability to revoke access instantly.  That idea became GPUShare.

Along the way I learned Flask inside out, dove deep into SQLAlchemy, built a CLI to manage the deployment, created a Tkinter GUI to control the host agent, and even wrote my own code‑safety scanner to block malicious Python.  What started as a weekend fun evolved into a robust, modular system.

## Feature Overview

GPUShare has grown into a full‑featured application.  Here’s a tour of the main capabilities:

###  Secure Registration and Login

- **Email + Password + Random Token** – New users register with a username, email and password.  They receive an 8‑character token by email.  This random token must be presented on every login attempt (a bit like a second password).
- **One‑Time Password (OTP)** – After submitting your credentials and token, the server emails a 6‑digit OTP.  You must enter it within 5 minutes to complete the login.  OTPs are cleared after use.
- **Two‑Factor Authentication** – All you need is access to your email.

###  Role‑Based Access Control

Users belong to one of four roles, each unlocking different actions:

| Role | Description | Typical Actions |
|------|-------------|-----------------|
| **Client** | The default role for new users.  Clients can browse available GPUs, request access, see their request history and create API tokens. | Browse GPUs, submit code, track request status, manage personal API tokens. |
| **Moderator** | Moderators review access requests.  They can approve, deny or request changes.  Moderators are appointed by admins. | View pending requests, approve/deny, flag suspicious code. |
| **Admin** | Admins run the show.  They can promote or demote moderators, ban or unban users, register other admins (except superadmins), and manage all GPUs. | User management, GPU oversight, token oversight, respond to escalations. |
| **Superadmin** | A special admin.  There must always be at least one superadmin.  Only a superadmin can demote or ban an admin, and superadmins cannot be demoted or removed.  They also approve any administrative actions against other admins. | Final authority on admin actions, handle approval requests, ensure continuity. |

###  GPU Hosting Without Faking It

Owners cannot register GPUs through the web UI.  This is deliberate.  In earlier versions, users could manually add GPUs via a form, which opened the door to people fabricating specs.  Now, the **only way to register a GPU is to run the host agent script** on the machine that physically owns the card.  The agent collects real hardware information (name, memory, driver version, UUID) and sends it to the server, which either registers the GPU or reconnects it if it was previously registered.

Note: Compile your python client.py code to you specifications so the client or your user can't just pass there fabricated specs via api call with api bearer.

Once registered, each GPU can be marked **idle** or **busy**, disconnected, or updated with heartbeat messages.  The platform tracks uptime and usage time, and the UI clearly shows if a GPU is **Active**, **Idle**, **Disconnected** or **Unavailable** based on heartbeats.

###  Code Submission and Safety Checks

When clients request access, they can attach Python code either by pasting it into a text box or uploading a `.py` file.  The code undergoes two safety scans:

1. **Static analysis via an AST visitor** – This custom scanner rejects imports of dangerous modules (`os`, `sys`, `subprocess`, `shutil`, `socket`, etc.) and disallows calls to functions like `eval`, `exec` and file operations.  If any of these appear, the request is automatically denied.
2. **Automated pattern matcher** – A secondary scan looks for risky patterns (e.g. shell escape sequences, `rm -rf`, attempts to open network sockets).  You can tweak these patterns in `gpushare_app/utils/security.py` to suit your threat model.

Only after passing both scans does the request land in a moderator queue.  Moderators review the code, verify the purpose, and either approve or deny the request.  Approved requests automatically expire after a set time (default one hour), ensuring a GPU isn’t hogged indefinitely.

###  API Tokens and Automation

Every user can generate API tokens.  These are long, random strings stored hashed in the database.  Tokens can have an optional expiry time.  With a token you can authenticate to the JSON API and the host agent without going through the OTP flow.  Tokens can be refreshed or revoked at any time via the web UI or API.  When a token is revoked, all sessions using it are immediately invalidated.

The API currently exposes endpoints for login, OTP verification, listing available GPUs, registering and reconnecting GPUs, updating GPU statistics, toggling idle state, fetching token metadata, refreshing tokens and revoking them.  See the [API section](#the-python-client-library) for concrete examples.

###  Light/Dark Mode with a Polished UI

The front end is built with **Bootstrap 5** and a theme inspired by **Bootswatch**.  A small button in the navigation bar toggles between light and dark mode.  The app remembers your choice using localStorage, so it sticks across sessions.  Cards have rounded corners and shadows, tables are striped, and forms include client‑side validation.  The admin dashboard separates users, GPUs and approval requests into neat cards.

###  Pluggable Storage and Database Back‑Ends

Out of the box GPUShare saves uploads to the local filesystem.  You can switch to **Nextcloud**, **Google Cloud Storage**, **Amazon S3** or **Cloudflare R2** by setting `STORAGE_PROVIDER` in your `.env`.  Each provider uses its own set of environment variables (`NEXTCLOUD_URL`, `GCS_CREDENTIALS_JSON`, `AWS_ENDPOINT_URL`, etc.).  If you’d rather use PostgreSQL or MySQL instead of SQLite, set `DATABASE_URL` accordingly and install the appropriate driver (`psycopg2-binary` or `pymysql`).

---

## Architecture and Technology Stack

The server side is a classic **Flask** application using the application factory pattern.  Each logical area authentication, GPU management, admin tools, API endpoints, token management is encapsulated in a **Blueprint**.  The ORM is **SQLAlchemy**, with **Flask-Login** for sessions and **Flask-Mail** for email notifications.  I rely on **Jinja2** templates for HTML rendering and **Bootstrap** for styling.  Configuration comes from a `.env` file loaded via `python-dotenv`.

On the client side, there are two major pieces:

1. **The GPU Host Agent** – A Python script that runs on the machine with the GPU.  It gathers GPU statistics via [`GPUtil`](https://pypi.org/project/gputil/), registers the GPU with the server, and sends periodic heartbeats.  It includes a simple Tkinter GUI for controlling the agent, refreshing tokens and executing code locally for testing.
2. **The [`gpushare`](https://pypi.org/project/gpushare) Python library** – A PyPI package that wraps the JSON API and provides high‑level methods to authenticate, list GPUs, register GPUs, submit code requests, manage API tokens and switch roles.  It’s great for building scripts or integrating GPUShare into a CI pipeline.  Note that, as of version 0.1.11, the [`GPUShare`](https://pypi.org/project/gpushare/) library warns that moderator functionality is still incomplete, but I have implemented it and routes are working.

I chose this stack because Flask is lightweight and flexible, SQLAlchemy offers a nice compromise between raw SQL and an overbearing ORM, and Tkinter ships with Python so I didn’t have to require external GUI frameworks.  Plus, the whole thing runs happily on Linux and Windows.

---

## Installation and Configuration

Getting [GPUShare](https://github.com/Srimany123/gpuShareApp/) up and running involves a few steps.

### 1. Clone the Repository

```bash
git clone https://github.com/Srimany123/gpuShareApp
```

### 2. Set Up a Virtual Environment

I always recommend isolating your Python dependencies.  Use `venv` or your favourite tool:

```bash
python3 -m venv gpushare
source venv/bin/activate  # On Windows use `venv\Scripts\activate`
pip install -r requirements.txt
```

### 3. Configure Environment Variables

GPUShare uses environment variables for secrets and configuration.  Copy the sample file and edit it:

```bash
cp env.example .env

# Then open .env in your editor and customise:
SECRET_KEY=change-me-to-a-random-string
MAIL_SERVER=smtp.example.com
MAIL_PORT=587
MAIL_USERNAME=your-email@example.com
MAIL_PASSWORD=your-email-password
MAIL_DEFAULT_SENDER="GPUShare <noreply@example.com>"
BASE_URL=http://localhost:5000

# Database (leave blank for SQLite)
DATABASE_URL=postgresql+psycopg2://user:password@localhost/gpushare

# Storage provider: local, nextcloud, gcs, s3, r2
STORAGE_PROVIDER=local

# Nextcloud settings (if using nextcloud)
NEXTCLOUD_URL=https://cloud.example.com/remote.php/dav/files/username
NEXTCLOUD_USERNAME=your-username
NEXTCLOUD_PASSWORD=your-password

# Google Cloud Storage settings (if using gcs)
STORAGE_BUCKET=your-bucket-name
GCS_CREDENTIALS_JSON=/absolute/path/to/gcs-credentials.json

# S3/R2 settings (if using s3 or r2)
AWS_ACCESS_KEY_ID=your-access-key
AWS_SECRET_ACCESS_KEY=your-secret-key
AWS_ENDPOINT_URL=https://<region>.r2.cloudflarestorage.com  # Only for R2
```

Save the file.  The application will load these values on startup.

### 4. Initialise the Database and Create an Admin

Run the CLI to set up your database tables and bootstrap a superadmin:

```bash
python argument.py init-db
python argument.py create-superadmin
```

You’ll be prompted for an email and password.  After submitting, the server will send a 6‑digit OTP to your email (and print it to the console if mail fails).  Enter the OTP to confirm your superadmin account.  This is important—GPUShare refuses to run unless at least one admin or superadmin exists.

You can create additional admins later:

```bash
python argument.py create-admin
```

### 5. Run the Server

Start the development server with:

```bash
python argument.py run-server --host 0.0.0.0 --port 5000
```

Open your browser and navigate to `http://localhost:5000`.  If everything is working you’ll see the landing page.  Feel free to reverse proxy through nginx or Apache if deploying to production.  Don’t forget to secure your site with HTTPS.

---

## Running the GPU Host Agent

Now for the fun part of bringing your GPU online!  The host agent script starts a small execution agent on port 6000, registers the GPU with the server and then sends heartbeat updates.

### Quick Start

1. **Copy the agent to your GPU machine.**  The script is self‑contained, but it does require Python 3 and the `requests` and `GPUtil` packages (`pip install requests gputil`).
2. **Launch the script.**  Run it with Python.  A Tkinter window titled **“GPUShare Agent Controller + Execution Agent”** appears (see screenshot below).  It looks like this:

![GPUShare Agent Controller GUI](./clientAgentGUI.png)

3. **Enter your server URL.**  This should point to your GPUShare server, e.g. `https://gpushare.srimanhq.com`.  There’s a handy **Ping Server** button that pings the hostname and tells you if it’s reachable.
4. **Paste your API token.**  You can generate an API token from the web UI under **API Tokens**.  Copy it, paste it into the **API Token** field and click **Validate**.  If the token is valid you’ll see a green **Status** message and the **Start Host Agent** button will enable.
5. **Start the agent.**  Click **Start Host Agent**.  The script collects information about your GPU (using GPUtil) and sends it to the server at `/api/register_gpu`.  If this is the first time you’re running the agent, the server registers a new GPU.  If you previously registered this GPU and it disconnected, the server reconnects it.  You’ll see heartbeat messages updating every 20 seconds.  The coloured dot (to the left of “Heartbeat”) blinks to show the connection is alive.
6. **Interact with the agent.**  The GUI provides buttons to:
   - **Set GPU Idle / Set GPU Active** – Toggle the idle flag.  Idle GPUs still show up in lists but may be passed over by moderators if marked idle.
   - **List Devices** – Opens your GPUShare server in a browser tab at the **My Hosted GPU** page so you can see the GPU you just registered.
   - **Get API Key** – Opens the **API Tokens** page where you can generate or revoke tokens.
   - **Refresh Token** – Refreshes the expiry of the current token via `/api/refresh_token`.
   - **Kill Token** – Revokes the current token.  Do this if you suspect your token has leaked.
   - **Execute Code** – Opens a simple text box where you can run arbitrary Python on your local machine, using the execution agent’s `/execute_code` endpoint.  Useful for quick tests, though note that this runs locally, not on the GPU you’re hosting.

When you click **Stop Agents**, both the execution agent and host agent stop.  The server sees the GPU as disconnected until you start the agent again.

### When GPUtil Isn’t Available

If your machine doesn’t have a supported GPU or you don’t have `GPUtil` installed, the agent sends a payload with an `"error"` key.  The server will still register the device with a default name (“Unnamed GPU”), but obviously you won’t be able to run GPU workloads.  To fix this, install GPUtil (`pip install gputil`) and make sure your GPU drivers are up to date.

### Heartbeats and Uptime

Once registered, the agent sends a POST request to `/api/update_gpu_stats` every 20 seconds with the GPU ID and usage time (in seconds).  The server updates the `last_update` timestamp and usage counter.  If no heartbeat arrives within a configurable threshold (default 60 seconds), the server marks the GPU as **Unavailable**.  You can customise the heartbeat interval in the script if you want shorter or longer intervals.

---

## Using the Web Interface

After logging in via OTP, you land on the home page.  Depending on your role you’ll see different menu items.  Here’s a quick tour of the main pages:

### Home

The landing page welcomes you with a brief description of GPUShare and a call‑to‑action button if you’re not logged in.  The nav bar includes **Login** and **Register** (if logged out) or **My Hosted GPU**, **Available GPUs**, **My Requests**, **API Tokens** and possibly **Admin** (if you’re an admin or superadmin).  The 🌗 toggle in the top right switches themes.

### Register / Login / OTP

- **Register** – Choose a username, email and password.  You’ll receive a random 8‑character token via email.  Keep this safe it’s your second factor.  If mail fails, the token prints to the server console. In that case contact the admin to remove the user with that email or simply register with different email.
- **Login** – Enter your email, password and random token.  The server will send an OTP (also via email and console).  You must enter it to finish logging in.
- **Verify OTP** – Enter the 6‑digit OTP.  A successful verification logs you in and clears the OTP.

### My Hosted GPU

If you’ve registered GPUs via the host agent, they appear here.  For each GPU you’ll see its ID, name, connection status, idle/busy flag and usage time.  Click **View Requests** to see any access requests.  You can approve or deny requests here, but moderators and admins may also step in.

There is **no button to add GPUs manually**.  All registration is done through the host agent script to ensure authenticity.

### Available GPUs

Lists all GPUs that are connected, not idle, and not hosted by you.  You can search by name.  Click **Request Access** to submit a request.  You’ll see a form where you can paste Python code or upload a `.py` file.  After submission the code is scanned for unsafe patterns and placed in the moderator queue.

### My Requests

Shows all access requests you’ve made and their statuses: **Requested**, **Pending**, **Approved** or **Denied**.  Approved requests display an expiry time.  Once expired, you must request again.

### Admin Dashboard

Admins and superadmins see this page.  It contains:

1. **Users table** – Lists all users with their roles, activity state and action buttons.  Admins can promote clients to moderators, demote moderators, ban/unban users and promote other admins (with approval).  Superadmins see additional buttons to demote admins or ban them; such actions trigger approval requests that only superadmins can finalise.
2. **Hosted GPUs** – A list of all GPUs on the platform, with status and usage columns.
3. **Approval Requests** (superadmins only) – Shows pending admin‑on‑admin actions.  Superadmins can approve or deny these.

### API Tokens

Here you can create new tokens, refresh their expiry and revoke them.  When creating a token you can specify how many hours it should be valid.  The token table shows creation and expiry dates.  Actions are performed via AJAX so you don’t have to reload the page.

---

## The Python Client Library

The [gpushare PyPI package](https://pypi.org/project/gpushare/) wraps the JSON API in an easy‑to‑use class.  It allows you to authenticate via OTP, manage tokens, switch roles (client, owner, admin, moderator) and perform GPU operations:

```python
from gpushare import GPUShareClient

client = GPUShareClient("https://your-gpushare-server.com")

# Login via the OTP flow
client.login("your.email@example.com", "your_password", "8CHARTOKEN")
# (You’ll be prompted to enter the OTP sent to your email)

# Switch to owner mode
client.switch_mode("owner")

# Back to user mode to list available GPUs
client.switch_mode("user")
print(client.list_available_gpus())

# Create a new API token with 24‑hour expiry
token = client.create_api_token(expires_in={"hours": 24})
print(token)
```

As of [gpushare](https://pypi.org/project/gpushare/) version 0.1.11 the library supports switching between `user`, `owner`, `admin` and `moderator` roles, moderator functionality is bit buggy. Keep an eye on the PyPI release notes for updates.

---

## Extending and Customising GPUShare

GPUShare is designed to be a starting point.  Here are a few ideas for taking it further:

1. **Add more storage providers** – Extend `gpushare_app/cloud/storage.py` with a new class for your provider (Azure Blob Storage or something of your choice).  Implement `upload_file()` to call your provider’s SDK.
2. **Integrate hardware monitoring** – Use `nvidia-smi` or AMD’s ROCm tools to expose temperature, clock speeds and power draw.  Display these metrics on the GPU detail page and send alerts if thresholds are exceeded.
3. **Billing and credit system** – Introduce a credit system where hosting GPUs earns credits and consuming GPUs spends them.  Track usage by seconds or by tokens.  You could even integrate cryptocurrency micro‑payments if you’re feeling adventurous.
4. **Better code execution environment** – Currently, code execution happens wherever the GPU is located and uses `exec()`.  You could integrate Docker or a sandbox like `nbsandbox` to run code in isolated containers.  This would allow more flexible language support (R, Julia, etc.).
5. **Redis caching and real‑time dashboards** – Use Redis to cache frequently accessed data (e.g. GPU status) and push updates to the UI via WebSockets.  Build a real‑time dashboard that shows active GPUs, pending requests and system health.
6. **Full moderator workflow** – The original monolithic project included a code review UI.  Port this into the modular version so moderators can view submitted code, leave comments, request revisions and approve/deny within the browser.

Contributing in a Opensource Project or Collaborating Opensource is Valuable for you in learning and For your resume for showing your technical and collaborating skills. If you implement something cool, send a pull request!  I’d love to see how other people extend GPUShare.

---

## Troubleshooting and FAQ

**Q: I get a 400 error when registering a GPU.**

A: The server used to require a `name` in the payload.  In the current version it defaults to “Unnamed GPU” if the name is missing.  If you still get a 400, check that your API token is valid and that your payload includes a `gpu_info` object.  If `GPUtil` isn’t available, the script sends an `"error"` field which the server ignores.

**Q: The GUI says “Unknown” when I ping the server.**

A: Ensure you entered the correct protocol (http vs https) and that your firewall allows ICMP echo requests.  You can still proceed without a ping result; click Validate with your token and see if it works.

**Q: My GPU shows as “Unavailable” in the web UI.**

A: The server marks a GPU unavailable if it hasn’t received a heartbeat within 60 seconds.  Make sure the agent is running and not blocked by a firewall.  You can adjust the heartbeat interval in the client script (`host_agent_loop`) to suit your network conditions.

**Q: How do I recover my random token?**

A: Each time you register a user, a new 8‑character token is emailed to you and printed in the server logs.  There isn’t currently a “forgot token” flow; if you lose it, re‑register with a different email or ask an admin to reset your account.

**Q: Why can’t I register a GPU via the website?**

A: To prevent users from faking GPU specs.  All GPUs must be registered via the host agent script, which collects real hardware information.  The web interface is for browsing, requests, approvals and administration only.

**Q: What about Windows support?**

A: The server runs everywhere Python does.  The host agent uses Tkinter, which is included with the standard Python distribution on Windows.  GPUtil works with NVIDIA cards on Windows.  Just remember to open port 6000 in your local firewall if the server needs to reach back.

---

## Final Thoughts

I started GPUShare to scratch my own itch, but it turned into something valuable to me. I have learned role‑based permissions, importance of secure defaults, and the joy of turning idle hardware into something useful for friends.



I hope this README helps you understand and appreciate the design decisions I made.  Whether you’re running GPUShare for your tinkering, a local makerspace, or just a couple of friends, I’m excited to see what you build with it.  Feel free to fork the repo, submit issues, and contribute back.  Happy sharing!
