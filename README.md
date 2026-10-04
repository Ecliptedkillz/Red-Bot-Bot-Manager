# BotManager

A web portal for running multiple Discord bots with modular cogs. New bots use discord.py; imported Redbot instances run in their existing Redbot Python environment so their native cogs and data remain compatible.

## Run

Python 3.11 or newer:

```powershell
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt
.venv\Scripts\python run.py
```

Open **http://127.0.0.1:8765** and sign in with your account. On the first run, the terminal prints the initial administrator username and password. The portal runs on localhost behind Caddy. It loads the project `.env` automatically; existing environment variables take precedence. For a different port, change `BOTMANAGER_PORT` in `.env` (or use `--port 9000` for a standalone run). Sessions expire after 12 hours and reset when the portal restarts.

You can run `python run.py` without installing dependencies to try **Demo** mode. Demo processes simulate cog loading and never execute uploaded code or connect to Discord.

## HTTPS at bots.eclipted.com

The included `Caddyfile` proxies **https://bots.eclipted.com** to the portal at `127.0.0.1:8765`. Caddy handles automatic HTTPS certificates and HTTP redirects. See [Caddy automatic HTTPS](https://caddyserver.com/docs/automatic-https).

1. Point the DNS A record for `bots.eclipted.com` at this machine's public IPv4 address. If you add an AAAA record, it must point to a reachable IPv6 address on this machine.
2. Allow inbound TCP **80** and **443** in Windows Firewall. If behind a router, forward those ports to this machine. The Python backend stays on loopback; it does not need a public firewall rule.
3. Download Windows `caddy.exe` from [Caddy](https://caddyserver.com/download) and put it beside `start.bat`. Alternatively install it on PATH, put it in `bin/`, or set `CADDY_EXE` to its full path in `.env`.
4. Open `.env`. It already contains a generated portal password and the public URL. On a new checkout, copy `.env.example` to `.env` and set `BOTMANAGER_PASSWORD` to a long random password.
5. Double-click **start.bat**, or run `./start.bat` from PowerShell. It opens one new Windows Terminal window with **BotManager** and **Caddy** tabs. Both show their service output. Caddy validates its configuration before starting.

Windows Terminal (`wt.exe`) is required; the batch file reports missing prerequisites. Caddy is not bundled. Keep both services running; press Ctrl+C inside each tab to stop them. Stop BotManager with Ctrl+C before closing the window so managed bots can shut down cleanly. The launcher does not change DNS, router settings, or firewall rules.

`.env` settings:

| Variable | Purpose |
| --- | --- |
| `BOTMANAGER_PORT` | Loopback backend port; used by both Python and Caddy |
| `BOTMANAGER_PUBLIC_URL` | Exact HTTPS origin allowed by the portal; defaults here to `https://bots.eclipted.com` |
| `BOTMANAGER_ADMIN_USERNAME` | Initial administrator username; defaults to `admin` |
| `BOTMANAGER_PASSWORD` | Seeds the first administrator password only; empty generates it on first run |
| `CADDY_EXE` | Optional full path to Caddy, without surrounding shell commands |

To change the domain, update both `Caddyfile` and `BOTMANAGER_PUBLIC_URL`. `.env` values are literal `KEY=value` entries, optionally quoted; do not use shell commands or inline comments. The portal accepts its configured public host and exact HTTPS origin without trusting client-supplied forwarding headers. Public sessions use Secure cookies; local HTTP access still works.

## Use

Click a bot card or **Open portal** to open that bot's dedicated page. Its Overview, Console, Cogs, and Settings tabs have their own URLs. Console shows live runtime output and startup progress; the controls above the tabs start, stop, or restart that bot. Settings drafts survive automatic refreshes. Browser back/forward and bookmarked links work, including after signing in.

Search the fleet by name or runtime and narrow it by status. Console controls copy output or pause auto-scroll while you inspect older lines. Password fields include Show/Hide controls. Deletion uses an in-page confirmation with Cancel focused first; Escape cancels it. Dialogs support backdrop dismissal, keyboard focus, custom scrollbars, and sticky headings/actions. Notifications can be dismissed and pause their timer while hovered or focused. Layouts adapt to phone, tablet, and desktop widths, and respect reduced-motion preferences.

| Page | URL path |
| --- | --- |
| Fleet | `/` |
| Account administration | `/admin` |
| Fleet cog library | `/cogs` |
| Fleet activity | `/logs` |
| Create / import a bot | `/bots/new`, `/bots/import` |
| Add a custom cog | `/cogs/new` |
| Bot overview | `/bots/<bot-id>` |
| Bot console | `/bots/<bot-id>/console` |
| Bot cog controls | `/bots/<bot-id>/cogs` |
| Bot configuration | `/bots/<bot-id>/settings` |
| Cog JSON editor | `/bots/<bot-id>/cogs/<module>/settings` |

For example, Eclipted's console is `https://bots.eclipted.com/bots/58484bb5e23a/console`. Bot IDs remain stable when you rename a bot. Caddy forwards these routes to Python without additional configuration. Restart the portal after updating its server code to enable serving direct links; sign in and start your bots again after the restart.

1. Create a bot with a name, prefix, and runtime.
2. For Discord mode, enter a bot token from the Discord Developer Portal. Enable **Message Content Intent** under Bot → Privileged Gateway Intents, and invite the bot to your server with the permissions its cogs need.
3. Start the bot; its status changes from starting to running after Discord connects. Connection errors appear in Activity logs.
4. Open Cogs to start (load), stop (unload), or reload a cog without restarting the bot. Successful changes also update which cogs load at the next start.
5. Open JSON settings beside a cog to save an arbitrary JSON object scoped to that bot and module.

Bots have independent processes. Stop a bot before editing its token, prefix, name, or mode. Restart replaces its process and reloads enabled cogs. Closing the portal with Ctrl+C stops all managed bots. Bots do not automatically start when the portal opens.

Built-in cogs:

- `cogs.general`: `!ping`, `!hello`; optional JSON setting `{"greeting": "Hello from my bot!"}`.
- `cogs.moderation`: `!clear 5`; requires Manage Messages for both the user and bot, and limits requests to 100 messages.
- discord.py also supplies `!help`. Substitute your configured command prefix.

## Accounts and permissions

Sign in at the normal portal URL; passwords are submitted by POST and never belong in a URL. The router is bundled into `app.js`, so a missing standalone `routes.js` cannot break startup. After upgrading, stop the old BotManager process with Ctrl+C and restart it to activate the new account API. Sign in as `admin` with the initial password from `.env`, then start your bots again.

Open **Accounts** at `/admin` to create accounts, change passwords, disable accounts, and assign permissions. Administrators have full access. Members receive site permissions for creating/importing bots and viewing/uploading shared cogs, plus bot permissions for viewing, process controls, console logs, cog controls, JSON reads/writes, bot configuration, and deletion. Imports, uploaded cogs, and bot configuration grant powerful access and should go to trusted operators.

Bot defaults apply to every bot. A per-bot override replaces those defaults; an empty override denies access to that bot. Every bot action also requires its View permission. Hidden bots are excluded from API state as well as the interface, and direct API requests enforce permissions. A member who creates or imports a bot receives full permissions for that new bot.

Editing an account revokes its existing sessions, including when changing permissions, disabling it, or resetting its password. The last enabled administrator cannot be deleted, disabled, or demoted. Passwords are stored as salted scrypt hashes in `data/accounts.json`; changing `.env` does not reset an existing account.

If your old password appeared in a URL, change it in Accounts. For local password recovery, stop the portal and run:

```powershell
.venv\Scripts\python run.py --reset-password admin
```

The command prompts for the new password without displaying it. New passwords must have at least eight characters. Restart the portal afterward. Back up `accounts.json` along with the other data files; do not delete it as a password-reset method.

## Import existing Redbot instances

Click **Import bot** next to Create bot and enter an instance data folder, for example:

```text
C:\Users\shimo\repo\Bot\botdata
C:\Users\shimo\repo\Bot\eclipteds
```

Import each folder separately. It must contain `core/settings.json` and `cogs/`. The optional Python path selects the environment where Redbot is already installed; the default is `%USERPROFILE%\redenv\Scripts\python.exe`, or `BOTMANAGER_RED_PYTHON` if set in `.env`. Redbot is not installed into the portal's virtual environment.

Imports copy tokens, all command prefixes, owner settings, enabled packages, installed cogs, third-party libraries, and saved cog data into `data/red_instances/<bot-id>/`. Historical logs and Python bytecode caches are skipped. References to paths within the original instance are relocated to the managed copy. The original is never moved or edited. Each copy uses a private instance registry under `data/red_instances/`; the existing Redbot registry is not changed. Importing the same source twice is rejected.

Stop the original before importing for a consistent snapshot. Keep it stopped when running its imported copy to avoid two processes using the same Discord account. Imports remain stopped until you click Start; imported tokens never appear in API responses.

Imported cards show **Redbot runtime**. Their cog library contains installed and bundled Redbot cogs, plus separate **Redbot JSON** entries for saved configuration. Start, stop, and reload use Redbot's native cog operations. Stop the bot before editing native JSON settings because Redbot caches its data. These editors expose the existing Redbot JSON structure, including configuration identifiers and guild/user scopes; preserve that structure when editing. Prefix changes in Bot settings replace the global prefix list with the new prefix; an unchanged prefix preserves the original list.

If your original launcher uses `--co-owner`, enter those user IDs under **Bot settings → Redbot co-owner user IDs**. The manager preserves them as launch arguments on each start/restart. This also supplies an explicit owner for team-owned applications that otherwise report “Bot doesn't have any owner set!”. IDs may be separated by commas or spaces; only assign these permissions to trusted operators.

For additional native cogs, use Redbot's Downloader or place a trusted Redbot package in the managed instance's `cogs/CogManager/cogs/` folder. The portal's custom `.py` upload template targets new discord.py bots. Paths pointing outside the source instance are preserved and may need manual adjustment. Importing does not guarantee that every third-party cog has compatible dependencies; startup errors appear in Activity logs.

## Custom cogs

Use Cog library → Add custom cog to paste Python or import a `.py` file. Give it a lowercase module name, such as `welcome`. Files are syntax-checked and must define `async def setup(bot)`. Loading in a real Discord bot verifies imports and setup. Uploaded code has the same permissions as your account, so only use trusted code.

```python
import discord
from discord.ext import commands

class Welcome(commands.Cog):
    def __init__(self, bot):
        self.bot = bot

    @commands.command()
    async def welcome(self, ctx):
        settings = self.bot.cog_store("custom_cogs.welcome").read()
        await ctx.send(
            settings.get("message", "Welcome aboard!"),
            allowed_mentions=discord.AllowedMentions.none(),
        )

async def setup(bot):
    await bot.add_cog(Welcome(bot))
```

Set `{"message": "Welcome to our community!"}` through the cog’s JSON settings. Reads happen on each invocation, so this example needs no reload after a setting change. Cogs that cache settings should reread them or be reloaded.

To update code, edit `data/custom_cogs/welcome.py` and click Reload. Duplicate uploads are rejected to avoid accidentally overwriting a cog. Install any extra Python dependencies into the same virtual environment. Custom cogs use [discord.py’s extension API](https://discordpy.readthedocs.io/en/stable/ext/commands/extensions.html); they can define `cog_unload` / `teardown` to clean up tasks and resources.

## JSON storage

```text
data/
  accounts.json                     # accounts, password hashes, permissions
  bots.json                         # bot configuration, tokens, enabled cogs
  custom_cogs/                      # uploaded Python modules
  settings/<bot-id>/<module>.json    # per-bot cog settings
  red_instances/<bot-id>/            # full imported Redbot data
  red_instances/<bot-id>.json        # private Redbot instance registry
```

Files are replaced atomically to avoid partially written JSON. `JsonStore` serializes threads sharing the same store instance; it does not provide cross-process transaction locking. Keep cog state in separate JSON files from portal-edited settings if the cog also writes frequently. Back up `data/` while bots are stopped. Deleting a bot removes its configuration but preserves its settings files. Logs are held in memory (last 300 lines per bot) and reset with the portal.

Tokens are stored locally in plaintext in `bots.json`, excluded from Git, omitted from API responses, and redacted from managed logs. Protect access to the data directory and `.env` (also excluded from Git). The portal has account authentication, server-enforced site and per-bot permissions, HttpOnly SameSite cookies, same-origin mutation checks, host validation, and login throttling. Grant executable cog uploads and imports only to trusted operators.

## Verify

```powershell
python -m unittest discover -s tests -v
node tests/routes.test.js
```

Tests exercise real demo subprocesses, cog controls, restart persistence, custom cog validation, JSON updates, token redaction, authentication, permission enforcement, account validation, session revocation, safe login forms, and HTTP access checks. Live Discord connectivity requires your own token and server.

On Windows with Edge and Node 22 or newer, run `node tests/browser-smoke.cjs` to check the portal in an isolated headless browser with a temporary demo instance. It tests direct links, login, bot-card navigation, back/forward, settings drafts and saves, cog JSON saves, console reloads, account creation, restricted member access, denied API actions, safe login with JavaScript disabled, fleet filtering, responsive layouts, confirmation cancellation/deletion, notifications above modals, and console controls. It does not use your real bot credentials or connect any bot to Discord.

An additional offline check uses an existing Redbot environment and a temporary synthetic instance to verify the native control bridge without connecting to Discord:

```powershell
C:\Users\shimo\redenv\Scripts\python.exe tests\check_red_runtime.py
```
