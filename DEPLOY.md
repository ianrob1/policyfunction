# Deploy PolicyFunction to Vercel (policyfunction.org)

Follow these steps to host the app on Vercel and use your domain **policyfunction.org**.

---

## Step 1: Push your code to GitHub

1. Create a new repository on [GitHub](https://github.com/new) (e.g. `policyfunction` or `quant-strategies`).
2. In your project folder, run:

   ```bash
   cd /Users/ianrobinson/Downloads/quant-strategies
   git init
   git add .
   git commit -m "Initial commit: PolicyFunction backtest app"
   git branch -M main
   git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
   git push -u origin main
   ```

   Replace `YOUR_USERNAME` and `YOUR_REPO_NAME` with your GitHub username and repo name.

---

## Step 2: Sign in to Vercel and import the project

1. Go to [vercel.com](https://vercel.com) and sign in (use **Continue with GitHub**).
2. Click **Add New…** → **Project**.
3. **Import** the GitHub repo you just pushed (e.g. `quant-strategies` or `policyfunction`).
4. Leave the defaults:
   - **Framework Preset:** Other
   - **Root Directory:** . (leave blank)
   - **Build Command:** leave empty (no build step)
   - **Output Directory:** leave empty
5. Click **Deploy**.

Wait for the first deployment to finish. You’ll get a URL like `https://your-project-xxx.vercel.app`.

---

## Step 3: Add your domain (policyfunction.org)

1. In the Vercel dashboard, open your project.
2. Go to **Settings** → **Domains**.
3. Under **Add**, type: **policyfunction.org**
4. Click **Add**.
5. Vercel will show DNS records you need to add at your domain registrar.

---

## Step 4: Configure DNS at your domain registrar

Where you bought **policyfunction.org** (e.g. Namecheap, GoDaddy, Google Domains, Cloudflare):

1. Open the **DNS** or **Domain management** section for **policyfunction.org**.
2. Add the record Vercel tells you. Usually it’s one of these:

   **Option A – A record (recommended)**  
   - Type: **A**  
   - Name: **@** (or leave blank for “root”)  
   - Value: **76.76.21.21**

   **Option B – CNAME (if Vercel shows it)**  
   - Type: **CNAME**  
   - Name: **@** or **www**  
   - Value: **cname.vercel-dns.com**

3. If you want **www.policyfunction.org** to work too, add:
   - Type: **CNAME**
   - Name: **www**
   - Value: **cname.vercel-dns.com**

4. Save the DNS changes. Propagation can take from a few minutes up to 24–48 hours.

---

## Step 5: Confirm the domain in Vercel

1. Back in Vercel → **Settings** → **Domains**.
2. Next to **policyfunction.org** you should see a status (Validating / Valid).
3. When it shows **Valid**, the domain is ready.
4. Open **https://policyfunction.org** in your browser; you should see PolicyFunction and the backtest form.

---

## What’s already set up in the repo

- **`api/backtest.py`** – Vercel serverless function that runs backtests (same logic as your local `/backtest`).
- **`vercel.json`** – Rewrites `/backtest` to `/api/backtest` so the frontend works without changes; sets 60s timeout for the backtest API.
- **`.vercelignore`** – Excludes large/local files from deployment.

The app runs as:

- **Static:** `index.html`, `favicon.png` served by Vercel.
- **API:** Backtest requests go to `/api/backtest` (exposed as `/backtest` via rewrite).

---

## Optional: Deploy from your machine with the Vercel CLI

1. Install the CLI: `npm i -g vercel`
2. In the project folder: `vercel` and follow the prompts (log in, link to a project or create one).
3. Production deploy: `vercel --prod`

You can still connect the same project to GitHub so future pushes auto-deploy.

---

## Troubleshooting

- **“Backtest API not found”** – Wait a minute after the first deploy, then hard-refresh. If it persists, check **Vercel** → **Functions** and open the latest logs for `api/backtest`.
- **Domain not working** – Confirm the DNS records match exactly what Vercel shows and wait for DNS propagation (up to 48 hours).
- **Backtest timeout** – The function has a 60s limit. Very long date ranges might hit it; shorten the range or we can tune later.
