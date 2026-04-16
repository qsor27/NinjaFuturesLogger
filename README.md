# NinjaFuturesLogger

A self-hosted web application for reviewing and analyzing your NinjaTrader 8 futures trades. It runs on your own machine, imports trade executions automatically as you trade, and gives you a searchable journal with charts and statistics.

---

## How It Works

Understanding the moving parts before you start makes every step obvious:

1. **NinjaTrader writes CSV files.** An indicator you install in NinjaTrader (`ExecutionExporter`) writes a CSV file every time you execute a trade. It writes to a folder on your hard drive that you choose.
2. **The app watches that folder.** A Docker container running on your machine monitors the same folder. The moment a new CSV appears, it imports the trades automatically.
3. **You open a browser.** The app is available at `http://localhost:8000`. No internet connection required after setup.

The critical connection is that **the folder NinjaTrader writes to and the folder the app watches must be the same folder.** Setting this up correctly is the most important part of the install.

---

## What You Need

- A Windows PC running NinjaTrader 8
- [Docker Desktop for Windows](https://www.docker.com/products/docker-desktop/) (free)
- About 10 minutes

---

## Step 1 — Install Docker Desktop

Docker Desktop is the software that runs the app in an isolated container on your machine. Think of it as a lightweight, self-contained environment — it keeps the app and all its dependencies from interfering with anything else on your PC.

1. Download Docker Desktop from [docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop/).
2. Run the installer. Accept all defaults.
3. Restart your PC if prompted.
4. After restarting, Docker Desktop will start automatically (look for the whale icon in your system tray).
5. Verify it's working: open a Command Prompt and run:
   ```
   docker --version
   ```
   You should see something like `Docker version 28.x.x`. If you get an error, make sure Docker Desktop is running.

> **Note:** Docker Desktop must be running whenever you want to use NinjaFuturesLogger. It starts with Windows by default after installation.

---

## Step 2 — Create Your Data Folder

This folder is where all your trade data lives — the database, the imported CSVs, and the logs. You will point both the app and the NinjaTrader indicator at this location.

### Pick a location

Choose a folder on a **local drive** (your C: drive or another internal/external hard drive). The location is entirely up to you.

**Avoid any folder that syncs to the cloud.** This means do not use:
- OneDrive (`C:\Users\YourName\OneDrive\...`)
- Dropbox
- Google Drive (with local sync)
- Box Drive
- iCloud Drive
- SharePoint synced folders

**Why this matters:** Sync software continuously monitors files and locks them while uploading. This can corrupt your trade database, cause the app to miss incoming CSVs, or prevent the app from starting. This is not a fixable edge case — it will cause silent data problems. Use a plain local folder.

**Recommended location:** Create a folder directly on your C: drive, for example:
```
C:\FuturesTradingLog
```

### Create the folder structure

Inside your chosen folder, create one subfolder called `inbox` and one called `config`. You can do this in File Explorer or by running these commands in a Command Prompt (adjusting the path if you chose a different location):

```
mkdir C:\FuturesTradingLog\inbox
mkdir C:\FuturesTradingLog\config
```

Your folder should look like this:
```
C:\FuturesTradingLog\
├── config\
└── inbox\        ← NinjaTrader will write CSV files here
```

The app will create all other subfolders (archive, logs, database) automatically on first run.

### Create the configuration file

The app requires a configuration file at `config\app.json` inside your data folder. Create a new file called `app.json` inside the `config` folder and paste in the following content exactly as shown:

```json
{
  "data_dir": "data",
  "db_path": "data/trading_log.db",
  "inbox_dir": "data/inbox",
  "archive_dir": "data/archive",
  "log_dir": "data/logs",
  "session": {
    "exchange_timezone": "America/Chicago",
    "trade_date_rollover": "16:00",
    "archive_job_time": "18:00"
  },
  "thread_pool": {
    "max_workers": 4
  },
  "scheduler": {
    "heartbeat_seconds": 60
  }
}
```

To create this file: open Notepad, paste the content above, then go to **File → Save As**, navigate to your `config` folder, set "Save as type" to **All Files**, and save the file as `app.json` (not `app.json.txt`).

Your folder should now look like this:
```
C:\FuturesTradingLog\
├── config\
│   └── app.json
└── inbox\
```

---

## Step 3 — Start the App

### Download the compose file

Download [`docker-compose.yml`](docker-compose.yml) from this repository. You only need this one file — you do not need to clone or download the entire project.

To download it directly: click the file name above, then click the **Raw** button on GitHub, then right-click the page and choose **Save As**. Save it anywhere convenient, such as your Desktop or your data folder.

### Edit the volume path

Open `docker-compose.yml` in Notepad. Find this line:

```
- C:/FuturesTradingLog:/app/data
```

Replace `C:/FuturesTradingLog` with the path to your data folder. **Use forward slashes (`/`), not backslashes (`\`), even on Windows.**

Examples:
- `C:/FuturesTradingLog:/app/data` — if your folder is `C:\FuturesTradingLog`
- `D:/Trading/Data:/app/data` — if your folder is `D:\Trading\Data`

Save the file.

### Pull and start the container

Open a Command Prompt in the folder where you saved `docker-compose.yml`. The easiest way: hold Shift and right-click the folder in File Explorer, then choose **Open PowerShell window here** (or **Open command window here**).

Run:
```
docker compose pull
docker compose up -d
```

The first command downloads the app image (a few hundred MB — one time only). The second starts it in the background. After a few seconds, verify it's running:

```
docker compose ps
```

You should see one container named `ninjafutureslogger` with status `Up (healthy)`.

Open your browser and go to:
```
http://localhost:8000
```

You should see the NinjaFuturesLogger interface. It will be empty until you start trading with the indicator installed.

---

## Step 4 — Install the NinjaTrader Indicator

The `ExecutionExporter` indicator runs inside NinjaTrader and writes a CSV file every time you execute a trade. It is a NinjaScript indicator — you import the source file once and NinjaTrader compiles it automatically.

### Get the indicator file

Download [`ExecutionExporter.cs`](ninjascript/ExecutionExporter.cs) from this repository. You can right-click the **Raw** button and save it anywhere (your Downloads folder is fine).

### Import into NinjaTrader 8

1. Open NinjaTrader 8.
2. In the top menu, go to **Tools → Edit NinjaScript → Indicator...**
3. The NinjaScript Editor window opens. In its menu, go to **File → Open**.
4. Navigate to where you saved `ExecutionExporter.cs` and open it.
5. Press **F5** (or click the **Compile** button in the toolbar). The Output tab at the bottom should show `Compile succeeded with 0 error(s), 0 warning(s)`.
6. Close the NinjaScript Editor.

---

## Step 5 — Connect NinjaTrader to the App

This step is the most important. The indicator needs to know exactly where to write its CSV files, and that location must match the `inbox` folder inside your data folder.

### Add the indicator to a chart

1. Open any chart in NinjaTrader (any instrument, any timeframe).
2. Right-click anywhere on the chart and choose **Indicators...**
3. In the Indicators window, find **ExecutionExporter** in the list on the left. Double-click it to add it, or select it and click **Add**.
4. The indicator's settings panel appears on the right side.

### Set the Export Path

In the indicator settings, find the **Export Path** field. Set it to the full path of your `inbox` folder — the one you created in Step 2.

For example, if your data folder is `C:\FuturesTradingLog`:
```
C:\FuturesTradingLog\inbox
```

If you used a different location, use that path instead. This must be the `inbox` subfolder, not the data folder itself.

Leave all other settings at their defaults.

5. Click **OK**.

### Why this path is the critical link

```
NinjaTrader → writes CSV → C:\FuturesTradingLog\inbox\
                                          ↕  (same folder)
Docker container → reads CSV → /app/data/inbox/
                                          ↕
                          App imports trades automatically
```

NinjaTrader writes files into `inbox`. The Docker container mounts your data folder and sees those same files as `/app/data/inbox`. If the paths don't align — for example, if the indicator writes to a different folder — no trades will ever appear in the app. Double-check this path carefully.

---

## Step 6 — Verify Everything Is Working

1. With the indicator on a chart, execute a trade in NinjaTrader (a real trade, a sim trade, or a replay will all work).
2. Open your `inbox` folder in File Explorer. You should see a CSV file named something like `NinjaTrader_Executions_20260415.csv` appear within a few seconds of the trade.
3. Open `http://localhost:8000` in your browser. Your trade should appear in the positions list within a few seconds.

If the CSV file appears in `inbox` but the trade does not appear in the app, the volume path in `docker-compose.yml` is likely pointing at the wrong folder. Re-check Step 3.

If no CSV file appears in `inbox` after trading, the indicator's Export Path is pointing at the wrong folder. Re-check Step 5.

---

## Keeping the App Updated

When a new version is released, update with two commands from the folder containing your `docker-compose.yml`:

```
docker compose pull
docker compose up -d
```

This downloads the new image and restarts the container. Your data folder and database are untouched — they live on your hard drive, outside the container.

---

## Troubleshooting

**The app won't start / container exits immediately**

Check the logs:
```
docker compose logs
```
The most common cause is a missing or malformed `app.json`. Make sure the file exists at `<your data folder>\config\app.json` and that the content is valid JSON (no trailing commas, correct quotes).

**No trades appear after trading**

Work through the chain:
1. Check `inbox` — is there a CSV file? If yes, the indicator is working. If no, the indicator's Export Path is wrong (Step 5).
2. If there is a CSV in `inbox` but no trades in the app, the volume path in `docker-compose.yml` is wrong (Step 3). The path on the left side of the `:` must exactly match your data folder.

**Port 8000 is already in use**

Something else on your machine is using port 8000. In `docker-compose.yml`, change `"8000:8000"` to `"8080:8000"` (or any other open port), then run `docker compose up -d` again. Access the app at `http://localhost:8080`.

**Docker Desktop is not running**

The container only runs while Docker Desktop is running. If you restart your PC, Docker Desktop starts automatically and the container restarts as well (it has `restart: unless-stopped`). If you manually stop Docker Desktop, restart it from the system tray or Start menu.

**I moved my data folder**

Update the volume path in `docker-compose.yml` to the new location, then run:
```
docker compose down
docker compose up -d
```
