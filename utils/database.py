
from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DATA_FILE = Path("data/tempvc_data.json")

@dataclass
class TempChannel:
    owner_id: int
    guild_id: int
    name: str
    user_limit: int = 0
    is_locked: bool = False
    is_hidden: bool = False
    waiting_room_id: Optional[int] = None
    chat_channel_id: Optional[int] = None
    region: Optional[str] = None
    blocked_users:  set = field(default_factory=set)
    trusted_users:  set = field(default_factory=set)
    muted_by_owner: set = field(default_factory=set)
    invited_users:  set = field(default_factory=set)
    panel_message_id: Optional[int] = None
    panel_channel_id: Optional[int] = None

@dataclass
class GuildConfig:
    jtc_channel_id: int
    category_id: int
    panel_channel_id: int
    admin_muted:      set  = field(default_factory=set)
    owner_warnings:   dict = field(default_factory=dict)
    penalized_owners: set  = field(default_factory=set)
    shared_panel_message_id: Optional[int] = None
    log_channel_id: Optional[int] = None

@dataclass
class UserVCMemory:
    """Persistent snapshot of a user's last VC settings, keyed by (guild_id, user_id)."""
    name:           Optional[str] = None   # custom name; None = use Discord default
    user_limit:     int           = 0
    is_locked:      bool          = False
    is_hidden:      bool          = False
    region:         Optional[str] = None
    trusted_users:  set = field(default_factory=set)
    blocked_users:  set = field(default_factory=set)
    muted_by_owner: set = field(default_factory=set)

class Database:
    def __init__(self):
        self._channels: dict[int, TempChannel] = {}
        self._configs:  dict[int, GuildConfig]  = {}
        # key: (guild_id, user_id)
        self._memories: dict[tuple[int,int], UserVCMemory] = {}
        self._load()

    def _load(self) -> None:

        if not DATA_FILE.exists():
            print("ℹ️  No existing data file — starting fresh.")
            return

        try:
            with open(DATA_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as exc:
            print(f"⚠️  Could not read {DATA_FILE}: {exc}  — starting fresh.")
            return

        for gid_str, cfg in data.get("guilds", {}).items():
            gid = int(gid_str)
            self._configs[gid] = GuildConfig(
                jtc_channel_id=cfg["jtc_channel_id"],
                category_id=cfg["category_id"],
                panel_channel_id=cfg["panel_channel_id"],
                admin_muted=set(int(x) for x in cfg.get("admin_muted", [])),
                owner_warnings={int(k): v for k, v in cfg.get("owner_warnings", {}).items()},
                penalized_owners=set(int(x) for x in cfg.get("penalized_owners", [])),
                shared_panel_message_id=cfg.get("shared_panel_message_id"),
                log_channel_id=cfg.get("log_channel_id"),
            )

        for cid_str, ch in data.get("channels", {}).items():
            cid = int(cid_str)
            self._channels[cid] = TempChannel(
                owner_id=ch["owner_id"],
                guild_id=ch["guild_id"],
                name=ch["name"],
                user_limit=ch.get("user_limit", 0),
                is_locked=ch.get("is_locked", False),
                is_hidden=ch.get("is_hidden", False),
                waiting_room_id=ch.get("waiting_room_id"),
                chat_channel_id=ch.get("chat_channel_id"),
                region=ch.get("region"),
                blocked_users=set(int(x) for x in ch.get("blocked_users", [])),
                trusted_users=set(int(x) for x in ch.get("trusted_users", [])),
                muted_by_owner=set(int(x) for x in ch.get("muted_by_owner", [])),
                invited_users=set(int(x) for x in ch.get("invited_users", [])),
                panel_message_id=ch.get("panel_message_id"),
                panel_channel_id=ch.get("panel_channel_id"),
            )

        for mem_key, mem in data.get("memories", {}).items():
            gid_str, uid_str = mem_key.split(":")
            key = (int(gid_str), int(uid_str))
            self._memories[key] = UserVCMemory(
                name=mem.get("name"),
                user_limit=mem.get("user_limit", 0),
                is_locked=mem.get("is_locked", False),
                is_hidden=mem.get("is_hidden", False),
                region=mem.get("region"),
                trusted_users=set(int(x) for x in mem.get("trusted_users", [])),
                blocked_users=set(int(x) for x in mem.get("blocked_users", [])),
                muted_by_owner=set(int(x) for x in mem.get("muted_by_owner", [])),
            )

        print(
            f"✅  Loaded {len(self._configs)} guild config(s), "
            f"{len(self._channels)} active temp VC(s), and "
            f"{len(self._memories)} VC memories from {DATA_FILE}"
        )

    def save(self) -> None:

        DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = DATA_FILE.with_suffix(".tmp")

        payload: dict = {"guilds": {}, "channels": {}, "memories": {}}

        for gid, cfg in self._configs.items():
            payload["guilds"][str(gid)] = {
                "jtc_channel_id":              cfg.jtc_channel_id,
                "category_id":                 cfg.category_id,
                "panel_channel_id":            cfg.panel_channel_id,
                "admin_muted":                 list(cfg.admin_muted),
                "owner_warnings":              {str(k): v for k, v in cfg.owner_warnings.items()},
                "penalized_owners":            list(cfg.penalized_owners),
                "shared_panel_message_id":     cfg.shared_panel_message_id,
                "log_channel_id":              cfg.log_channel_id,
            }

        for cid, ch in self._channels.items():
            payload["channels"][str(cid)] = {
                "owner_id":        ch.owner_id,
                "guild_id":        ch.guild_id,
                "name":            ch.name,
                "user_limit":      ch.user_limit,
                "is_locked":       ch.is_locked,
                "is_hidden":       ch.is_hidden,
                "waiting_room_id": ch.waiting_room_id,
                "chat_channel_id": ch.chat_channel_id,
                "region":          ch.region,
                "blocked_users":   list(ch.blocked_users),
                "trusted_users":   list(ch.trusted_users),
                "muted_by_owner":  list(ch.muted_by_owner),
                "invited_users":   list(ch.invited_users),
                "panel_message_id":ch.panel_message_id,
                "panel_channel_id":ch.panel_channel_id,
            }

        for (gid, uid), mem in self._memories.items():
            payload["memories"][f"{gid}:{uid}"] = {
                "name":          mem.name,
                "user_limit":    mem.user_limit,
                "is_locked":     mem.is_locked,
                "is_hidden":     mem.is_hidden,
                "region":        mem.region,
                "trusted_users": list(mem.trusted_users),
                "blocked_users": list(mem.blocked_users),
                "muted_by_owner":list(mem.muted_by_owner),
            }

        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            shutil.move(str(tmp), str(DATA_FILE))
        except OSError as exc:
            print(f"⚠️  Failed to save {DATA_FILE}: {exc}")
            if tmp.exists():
                tmp.unlink(missing_ok=True)

    def set_config(self, guild_id: int, config: GuildConfig) -> None:
        self._configs[guild_id] = config
        self.save()

    def get_config(self, guild_id: int) -> Optional[GuildConfig]:
        return self._configs.get(guild_id)

    def create(self, channel_id: int, data: TempChannel) -> TempChannel:
        self._channels[channel_id] = data
        self.save()
        return data

    def get(self, channel_id: int) -> Optional[TempChannel]:
        return self._channels.get(channel_id)

    def delete(self, channel_id: int) -> None:
        self._channels.pop(channel_id, None)
        self.save()

    def exists(self, channel_id: int) -> bool:
        return channel_id in self._channels

    def get_by_owner(
        self, guild_id: int, user_id: int
    ) -> Optional[tuple[int, TempChannel]]:
        for ch_id, ch in self._channels.items():
            if ch.guild_id == guild_id and ch.owner_id == user_id:
                return ch_id, ch
        return None

    # ── Memory helpers ──────────────────────────────────────────────────────

    def save_memory(self, guild_id: int, user_id: int, ch_data: TempChannel) -> None:
        """Snapshot the owner's current VC settings into persistent memory."""
        self._memories[(guild_id, user_id)] = UserVCMemory(
            name=ch_data.name,
            user_limit=ch_data.user_limit,
            is_locked=ch_data.is_locked,
            is_hidden=ch_data.is_hidden,
            region=ch_data.region,
            trusted_users=set(ch_data.trusted_users),
            blocked_users=set(ch_data.blocked_users),
            muted_by_owner=set(ch_data.muted_by_owner),
        )
        self.save()

    def get_memory(self, guild_id: int, user_id: int) -> Optional[UserVCMemory]:
        return self._memories.get((guild_id, user_id))

    def clear_memory(self, guild_id: int, user_id: int) -> None:
        self._memories.pop((guild_id, user_id), None)
        self.save()

db = Database()
