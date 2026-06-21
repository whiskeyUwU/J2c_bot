# TempVC Discord Bot

A **Join-to-Create** temporary voice channel bot for Discord, written in Python with **discord.py v2**.

---

## ✨ Features

| Button | What it does |
|--------|-------------|
| **NAME** | Rename your temp VC |
| **LIMIT** | Set a user limit (0–99; 0 = unlimited) |
| **PRIVACY** | Toggle channel lock — locked channels require trust/invite to join |
| **WAITING ROOM** | Spawn a linked waiting-room VC so users can queue up |
| **CHAT** | Spawn a linked text channel alongside your VC |
| **TRUST** | Give a user permanent access (bypasses lock) |
| **UNTRUST** | Revoke a user's trusted status |
| **INVITE** | One-time invite — sends the user a DM notification |
| **KICK** | Disconnect a user from your VC (button convenience + native drag-kick) |
| **REGION** | Change the voice server region |
| **BLOCK** | Deny a user from joining your VC |
| **UNBLOCK** | Remove a block |
| **CLAIM** | Claim ownership if the original owner left |
| **TRANSFER** | Hand ownership to another user in the VC |
| **DELETE** | Delete the VC + waiting room + text chat |

### 🔇 Mute Persistence (key feature)

The VC owner has **native Discord permissions** to right-click mute/deafen/kick anyone in their VC.

- When the owner **server-mutes** someone, the bot tracks that.
- When the muted user **leaves**, the bot automatically removes the server-mute so they aren't stuck muted globally.
- When the muted user **rejoins** that specific VC, the bot re-applies the mute.
- When the VC is **deleted**, all data (including the mute list) is reset — no database needed.

---

## 🚀 Setup

### 1. Prerequisites

- Python **3.10+**
- A Discord bot token from [discord.com/developers](https://discord.com/developers/applications)

### 2. Create the bot

1. Go to [Discord Developer Portal](https://discord.com/developers/applications) → **New Application**
2. Go to **Bot** → **Add Bot**
3. Under **Privileged Gateway Intents**, enable:
   - ✅ **Server Members Intent**
   - ✅ **Voice State Update** (already on by default)
4. Copy your **Bot Token**

### 3. Required Bot Permissions

When inviting the bot, grant it:
- `Manage Channels`
- `Move Members`
- `Mute Members`
- `View Channels`
- `Send Messages`
- `Read Message History`
- `Connect` / `Speak`

Or use this permission integer: **`285221968`**

Invite URL template:
```
https://discord.com/api/oauth2/authorize?client_id=YOUR_CLIENT_ID&permissions=285221968&scope=bot%20applications.commands
```

### 4. Install dependencies

```bash
pip install -r requirements.txt
```

### 5. Configure `.env`

```bash
cp .env.example .env
```

Edit `.env`:
```env
BOT_TOKEN=your_token_here

# Optional: fill in for instant slash command sync during development
GUILD_ID=your_server_id_here
```

### 6. Run the bot

```bash
python main.py
```

### 7. Configure your server with `/setup`

In your Discord server (as an admin), run:

```
/setup jtc_channel:#join-to-create  category:#Voice Channels  panel_channel:#vc-controls
```

| Parameter | Description |
|-----------|-------------|
| `jtc_channel` | The voice channel users join to get a temp VC |
| `category` | The category where temp VCs will be created |
| `panel_channel` | A text channel where control panels are posted |

---

## 📁 File Structure

```
tempvc-bot/
├── main.py                 ← Entry point
├── requirements.txt
├── .env.example
├── utils/
│   ├── database.py         ← In-memory data store
│   ├── channel_utils.py    ← Channel creation / permission helpers
│   └── panel_builder.py    ← Embed builder
└── cogs/
    ├── setup_cog.py        ← /setup and /tempvc-status commands
    ├── voice_cog.py        ← Voice state events (JTC + mute-persistence)
    └── panel_cog.py        ← All 15 TempVC button interactions
```

---

## 🔄 How Mute Persistence Works (technical detail)

```
Owner right-click mutes User A in temp VC
    └─► voiceStateUpdate fires: before.mute=False → after.mute=True
    └─► Bot adds User A to channel's muted_by_owner set

User A leaves the VC
    └─► voiceStateUpdate fires: before.channel=tempVC, after.channel=None
    └─► Bot calls member.edit(mute=False)  ← removes global server mute
    └─► User A STAYS in muted_by_owner set

User A rejoins the same VC
    └─► voiceStateUpdate fires: before.channel=None, after.channel=tempVC
    └─► Bot detects User A is in muted_by_owner
    └─► Bot calls member.edit(mute=True)  ← re-applies mute

VC is deleted
    └─► All channel data (including muted_by_owner) is erased from memory
```

---

## ⚠️ Notes

- The bot requires the **`Mute Members`** server permission to perform mute/unmute operations for persistence.
- All data is **in-memory** — it resets when the bot restarts or a VC is deleted. This is by design.
- The control panel buttons are **persistent** (survive bot restarts) but the data behind them resets, so actions on old panels after a restart will say "You don't own an active voice channel."
