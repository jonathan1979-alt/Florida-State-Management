import os
import io
import datetime
from collections import Counter, defaultdict
from typing import Optional

import discord
from discord.ext import commands
from discord import app_commands
from zoneinfo import ZoneInfo


# =========================================================
# SETUP
# =========================================================
intents = discord.Intents.all()
bot = commands.Bot(command_prefix="!", intents=intents)

OWNER_ID = 1440502528067244032  # your ID

@bot.tree.interaction_check
async def global_check(interaction: discord.Interaction) -> bool:
    if interaction.user.id != OWNER_ID:
        await interaction.response.send_message(
            "You can't use this bot.",
            ephemeral=True
        )
        return False
    return True
EST = ZoneInfo("America/New_York")

SECRET_CODE = "8464291234052"

bot_locked = False

# =========================================================
# IN-MEMORY DATA
# =========================================================
user_logs: dict[int, list[dict]] = {}

command_feed: list[dict] = []
error_feed: list[dict] = []
alerts_feed: list[dict] = []

command_usage: Counter = Counter()
daily_active_users: dict[str, set[int]] = defaultdict(set)
server_member_snapshots: dict[int, int] = {}

blacklisted_users: set[int] = set()
whitelisted_users: set[int] = set()
shadowbanned_users: set[int] = set()
custom_cooldowns: dict[int, int] = {}  # seconds
last_command_used_at: dict[int, datetime.datetime] = {}

MAX_FEED_ITEMS = 200


# =========================================================
# TIME / HELPERS
# =========================================================
def get_est_time() -> datetime.datetime:
    return datetime.datetime.now(EST)


def now_string() -> str:
    return get_est_time().strftime("%Y-%m-%d %I:%M %p %Z")


def add_alert(kind: str, message: str):
    alerts_feed.append({
        "kind": kind,
        "message": message,
        "time": get_est_time()
    })
    if len(alerts_feed) > MAX_FEED_ITEMS:
        alerts_feed.pop(0)


def trim_feed(feed_list: list, max_items: int = MAX_FEED_ITEMS):
    while len(feed_list) > max_items:
        feed_list.pop(0)


def build_embed(
    title: str,
    desc: str,
    color: discord.Color,
    member: Optional[discord.Member] = None,
    moderator: Optional[discord.Member] = None
) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=desc,
        color=color,
        timestamp=get_est_time()
    )

    if member:
        embed.set_thumbnail(url=member.display_avatar.url)

    if moderator:
        embed.set_footer(
            text=f"Action by {moderator}",
            icon_url=moderator.display_avatar.url
        )

    return embed


def add_log(
    user: discord.Member,
    action: str,
    reason: str,
    moderator: str,
    duration: Optional[str] = None
) -> int:
    user_logs.setdefault(user.id, [])
    log_id = len(user_logs[user.id]) + 1

    user_logs[user.id].append({
        "id": log_id,
        "action": action,
        "reason": reason,
        "mod": moderator,
        "time": get_est_time(),
        "duration": duration
    })

    return log_id


def resolve_color(color_key: str, custom_hex: Optional[str] = None) -> discord.Color:
    if color_key == "custom" and custom_hex:
        try:
            return discord.Color(int(custom_hex.replace("#", "").strip(), 16))
        except Exception:
            return discord.Color.blurple()

    mapping = {
        "red": discord.Color.red(),
        "orange": discord.Color.orange(),
        "yellow": discord.Color.yellow(),
        "green": discord.Color.green(),
        "blue": discord.Color.blue(),
        "purple": discord.Color.purple(),
        "pink": discord.Color.from_rgb(255, 105, 180),
        "white": discord.Color.from_rgb(245, 245, 245),
        "brown": discord.Color.from_rgb(139, 69, 19),
        "rose": discord.Color.from_rgb(255, 102, 178),
        "gold": discord.Color.gold(),
        "iceblue": discord.Color.from_rgb(173, 216, 230),
        "magenta": discord.Color.magenta(),
        "midnight": discord.Color.from_rgb(25, 25, 112),
        "blurple": discord.Color.blurple(),
        "pumpkin": discord.Color.from_rgb(255, 117, 24),
    }
    return mapping.get(color_key, discord.Color.blurple())


def color_display_name(color_key: str, custom_hex: Optional[str] = None) -> str:
    color_options = [
        ("🔴 Red", "red"),
        ("🟠 Orange", "orange"),
        ("🟡 Yellow", "yellow"),
        ("🟢 Green", "green"),
        ("🔵 Blue", "blue"),
        ("🟣 Purple", "purple"),
        ("🌸 Pink", "pink"),
        ("🤍 White", "white"),
        ("🤎 Brown", "brown"),
        ("🌹 Rose", "rose"),
        ("💛 Gold", "gold"),
        ("🩵 Ice Blue", "iceblue"),
        ("💖 Magenta", "magenta"),
        ("🌑 Midnight", "midnight"),
        ("💜 Blurple", "blurple"),
        ("🎃 Pumpkin", "pumpkin"),
        ("🎨 Custom Color (enter hex)", "custom"),
    ]

    if color_key == "custom":
        return f"🎨 Custom ({custom_hex})" if custom_hex else "🎨 Custom"

    for label, value in color_options:
        if value == color_key:
            return label

    return "💜 Blurple"


def build_announcement_embed(
    data: dict,
    color_key: str,
    custom_hex: Optional[str] = None
) -> discord.Embed:
    embed = discord.Embed(
        title=data["title"] or None,
        description=data["message"] or None,
        color=resolve_color(color_key, custom_hex),
        timestamp=get_est_time()
    )

    if data.get("image"):
        embed.set_image(url=data["image"])

    if data.get("thumbnail"):
        embed.set_thumbnail(url=data["thumbnail"])

    if data.get("footer"):
        embed.set_footer(text=f"{data['footer']} • {get_est_time().strftime('%I:%M %p')}")

    return embed


def user_history_embed(user_id: int, guild: Optional[discord.Guild] = None) -> discord.Embed:
    logs = user_logs.get(user_id, [])
    recent_commands = [x for x in command_feed if x["user_id"] == user_id][-10:]

    if guild:
        member = guild.get_member(user_id)
        display_name = str(member) if member else str(user_id)
        avatar_url = member.display_avatar.url if member else None
    else:
        display_name = str(user_id)
        avatar_url = None

    embed = discord.Embed(
        title=f"👤 User History — {display_name}",
        color=discord.Color.blurple(),
        timestamp=get_est_time()
    )

    if avatar_url:
        embed.set_thumbnail(url=avatar_url)

    embed.add_field(name="Warnings / Punishments", value=str(len(logs)), inline=True)
    embed.add_field(name="Blacklisted", value="Yes" if user_id in blacklisted_users else "No", inline=True)
    embed.add_field(name="Shadowbanned", value="Yes" if user_id in shadowbanned_users else "No", inline=True)

    cooldown_value = custom_cooldowns.get(user_id)
    embed.add_field(
        name="Custom Cooldown",
        value=f"{cooldown_value}s" if cooldown_value is not None else "None",
        inline=True
    )
    embed.add_field(
        name="Whitelisted",
        value="Yes" if user_id in whitelisted_users else "No",
        inline=True
    )

    if logs:
        lines = []
        for log in logs[-5:]:
            dur = f" • {log['duration']}" if log["duration"] else ""
            lines.append(
                f"`#{log['id']}` {log['action']} — {log['reason']}{dur}"
            )
        embed.add_field(
            name="Recent Mod Logs",
            value="\n".join(lines),
            inline=False
        )

    if recent_commands:
        lines = []
        for entry in recent_commands[-5:]:
            lines.append(
                f"`{entry['command']}` in {entry['guild']} • {entry['time'].strftime('%I:%M %p')}"
            )
        embed.add_field(
            name="Recent Commands",
            value="\n".join(lines),
            inline=False
        )

    return embed


# =========================================================
# DM SYSTEM
# =========================================================
async def send_dm(member: discord.Member, action: str, reason: str, guild: discord.Guild):
    try:
        embed = discord.Embed(
            title=f"⚠️ You were {action}",
            description=(
                f"**Server:** {guild.name}\n"
                f"**Reason:** {reason}\n\n"
                f"{get_est_time().strftime('Today at %I:%M %p %Z')}"
            ),
            color=discord.Color.from_rgb(255, 204, 0),
            timestamp=get_est_time()
        )

        # user's pfp
        embed.set_thumbnail(url=member.display_avatar.url)

        if guild.icon:
            embed.set_author(name=guild.name, icon_url=guild.icon.url)

        await member.send(embed=embed)
    except discord.Forbidden:
        pass
    except Exception:
        pass


# =========================================================
# COMMAND / ERROR TRACKING
# =========================================================
def log_command_usage(
    user_id: int,
    user_name: str,
    command_name: str,
    guild_name: str,
    guild_id: Optional[int]
):
    entry = {
        "user_id": user_id,
        "user_name": user_name,
        "command": command_name,
        "guild": guild_name,
        "guild_id": guild_id,
        "time": get_est_time()
    }
    command_feed.append(entry)
    trim_feed(command_feed)

    command_usage[command_name] += 1
    daily_active_users[get_est_time().strftime("%Y-%m-%d")].add(user_id)


@bot.listen("on_command")
async def on_prefix_command_log(ctx: commands.Context):
    log_command_usage(
        user_id=ctx.author.id,
        user_name=str(ctx.author),
        command_name=ctx.command.name if ctx.command else "unknown",
        guild_name=ctx.guild.name if ctx.guild else "DM",
        guild_id=ctx.guild.id if ctx.guild else None
    )


@bot.event
async def on_interaction(interaction: discord.Interaction):
    if interaction.type == discord.InteractionType.application_command:
        name = None
        if interaction.data:
            name = interaction.data.get("name")

        if name:
            log_command_usage(
                user_id=interaction.user.id,
                user_name=str(interaction.user),
                command_name=f"/{name}",
                guild_name=interaction.guild.name if interaction.guild else "DM",
                guild_id=interaction.guild.id if interaction.guild else None
            )

    await bot.process_application_commands(interaction) if hasattr(bot, "process_application_commands") else None


def log_error_entry(user_name: str, user_id: int, command_name: str, error_text: str):
    error_feed.append({
        "user_name": user_name,
        "user_id": user_id,
        "command": command_name,
        "error": error_text,
        "time": get_est_time()
    })
    trim_feed(error_feed)

    # alert on repeated failures
    same = [x for x in error_feed[-10:] if x["command"] == command_name]
    if len(same) >= 3:
        add_alert("error", f"Command `{command_name}` failed repeatedly.")


user_spam_tracker: dict[int, list[datetime.datetime]] = defaultdict(list)


def track_spam(user_id: int, display_name: str):
    now = datetime.datetime.utcnow()
    user_spam_tracker[user_id].append(now)
    user_spam_tracker[user_id] = user_spam_tracker[user_id][-5:]

    if len(user_spam_tracker[user_id]) == 5:
        diff = (user_spam_tracker[user_id][-1] - user_spam_tracker[user_id][0]).total_seconds()
        if diff < 5:
            add_alert("spam", f"User `{display_name}` may be spamming commands.")


# =========================================================
# GLOBAL CHECKS
# =========================================================
@bot.check
async def global_check(ctx: commands.Context):
    # adminpanel always allowed so you can unlock
    if ctx.command and ctx.command.name == "adminpanel":
        return True

    # shadowban = ignore silently
    if ctx.author.id in shadowbanned_users:
        raise commands.CheckFailure("shadowbanned")

    # blacklist unless whitelisted
    if ctx.author.id in blacklisted_users and ctx.author.id not in whitelisted_users:
        raise commands.CheckFailure("blacklisted")

    # bot lock unless whitelisted
    if bot_locked and ctx.author.id not in whitelisted_users:
        raise commands.CheckFailure("locked")

    # custom cooldown
    cooldown_seconds = custom_cooldowns.get(ctx.author.id)
    if cooldown_seconds is not None:
        last = last_command_used_at.get(ctx.author.id)
        now = get_est_time()
        if last:
            diff = (now - last).total_seconds()
            if diff < cooldown_seconds:
                raise commands.CheckFailure("cooldown")
        last_command_used_at[ctx.author.id] = now

    track_spam(ctx.author.id, str(ctx.author))
    return True


# =========================================================
# READY
# =========================================================
@bot.event
async def on_ready():
    try:
        await bot.tree.sync()
    except Exception as e:
        print(f"Slash sync failed: {e}")

    for guild in bot.guilds:
        server_member_snapshots[guild.id] = guild.member_count or 0

    print(f"Logged in as {bot.user}")


# =========================================================
# MODERATION COMMANDS
# =========================================================
@bot.command()
@commands.has_permissions(manage_messages=True)
async def warn(ctx, member: discord.Member, *, reason="No reason provided"):
    log_id = add_log(member, "WARN", reason, ctx.author.mention)

    embed = build_embed(
        "⚠️ Member Warned",
        f"**User:** {member.mention}\n"
        f"**Moderator:** {ctx.author.mention}\n\n"
        f"**Reason**\n{reason}\n\n"
        f"**Log ID:** #{log_id} • {now_string()}",
        discord.Color.from_rgb(255, 204, 0),
        member,
        ctx.author
    )

    await ctx.send(embed=embed)
    await send_dm(member, "warned", reason, ctx.guild)


@bot.command()
@commands.has_permissions(kick_members=True)
async def kick(ctx, member: discord.Member, *, reason="No reason provided"):
    await send_dm(member, "kicked", reason, ctx.guild)
    await member.kick(reason=reason)

    log_id = add_log(member, "KICK", reason, ctx.author.mention)

    embed = build_embed(
        "👢 Member Kicked",
        f"**User:** {member.mention}\n"
        f"**Moderator:** {ctx.author.mention}\n\n"
        f"**Reason**\n{reason}\n\n"
        f"**Log ID:** #{log_id} • {now_string()}",
        discord.Color.red(),
        member,
        ctx.author
    )

    await ctx.send(embed=embed)


@bot.command()
@commands.has_permissions(ban_members=True)
async def ban(ctx, member: discord.Member, *, reason="No reason provided"):
    await send_dm(member, "banned", reason, ctx.guild)
    await member.ban(reason=reason)

    log_id = add_log(member, "BAN", reason, ctx.author.mention)

    embed = build_embed(
        "🔨 Member Banned",
        f"**User:** {member.mention}\n"
        f"**Moderator:** {ctx.author.mention}\n\n"
        f"**Reason**\n{reason}\n\n"
        f"**Log ID:** #{log_id} • {now_string()}",
        discord.Color.dark_red(),
        member,
        ctx.author
    )

    await ctx.send(embed=embed)


@bot.command()
@commands.has_permissions(moderate_members=True)
async def timeout(ctx, member: discord.Member, minutes: int, *, reason="No reason provided"):
    until = discord.utils.utcnow() + datetime.timedelta(minutes=minutes)
    await member.timeout(until, reason=reason)
    await send_dm(member, "timed out", reason, ctx.guild)

    log_id = add_log(member, "TIMEOUT", reason, ctx.author.mention, f"{minutes}m")

    embed = build_embed(
        "⏳ Member Timed Out",
        f"**User:** {member.mention}\n"
        f"**Moderator:** {ctx.author.mention}\n"
        f"**Duration:** {minutes} minute(s)\n\n"
        f"**Reason**\n{reason}\n\n"
        f"**Log ID:** #{log_id} • {now_string()}",
        discord.Color.orange(),
        member,
        ctx.author
    )

    await ctx.send(embed=embed)


@bot.command()
@commands.has_permissions(manage_roles=True)
async def mute(ctx, member: discord.Member, minutes: int = None, *, reason="No reason provided"):
    role = discord.utils.get(ctx.guild.roles, name="Muted")

    if not role:
        role = await ctx.guild.create_role(name="Muted")
        for channel in ctx.guild.channels:
            try:
                await channel.set_permissions(role, send_messages=False, speak=False)
            except Exception:
                pass

    await member.add_roles(role, reason=reason)
    await send_dm(member, "muted", reason, ctx.guild)

    duration_text = f"{minutes}m" if minutes else "Permanent"
    log_id = add_log(member, "MUTE", reason, ctx.author.mention, duration_text)

    embed = build_embed(
        "🔇 Member Muted",
        f"**User:** {member.mention}\n"
        f"**Moderator:** {ctx.author.mention}\n"
        f"**Duration:** {duration_text}\n\n"
        f"**Reason**\n{reason}\n\n"
        f"**Log ID:** #{log_id} • {now_string()}",
        discord.Color.greyple(),
        member,
        ctx.author
    )

    await ctx.send(embed=embed)


@bot.command()
@commands.has_permissions(manage_roles=True)
async def unmute(ctx, member: discord.Member):
    role = discord.utils.get(ctx.guild.roles, name="Muted")

    if role and role in member.roles:
        await member.remove_roles(role)

    await ctx.send(embed=build_embed(
        "🔊 Unmuted",
        f"{member.mention} has been unmuted.",
        discord.Color.green(),
        member,
        ctx.author
    ))


# =========================================================
# LOG COMMANDS
# =========================================================
@bot.command()
async def expiredlogs(ctx):
    now = get_est_time()
    removed = 0

    for user_id in list(user_logs.keys()):
        new_logs = []
        for log in user_logs[user_id]:
            if (now - log["time"]).days <= 30:
                new_logs.append(log)
            else:
                removed += 1
        user_logs[user_id] = new_logs

    await ctx.send(f"🧹 Removed {removed} expired logs (older than 30 days).")


@bot.tree.command(name="viewlogs", description="View moderation logs for a user")
async def viewlogs(interaction: discord.Interaction, user: discord.Member):
    logs = user_logs.get(user.id, [])

    if not logs:
        await interaction.response.send_message("No logs found.", ephemeral=True)
        return

    embed = discord.Embed(
        title=f"📋 Moderation Logs — {user}",
        color=discord.Color.blue()
    )
    embed.set_thumbnail(url=user.display_avatar.url)
    embed.description = f"Total logs: {len(logs)}"

    for log in reversed(logs):
        time_str = log["time"].strftime("%Y-%m-%d %I:%M %p %Z")
        duration = f" • Duration: {log['duration']}" if log["duration"] else ""

        embed.add_field(
            name=f"[{log['id']}] {log['action']} — {time_str}",
            value=f"Reason: {log['reason']}{duration}\nMod: {log['mod']}",
            inline=False
        )

    embed.set_footer(text=f"{len(logs)} log(s) total")
    await interaction.response.send_message(embed=embed, ephemeral=True)


# =========================================================
# VC COMMANDS
# =========================================================
@bot.tree.command(name="joinvc", description="Join a voice channel")
async def joinvc(interaction: discord.Interaction, channel: discord.VoiceChannel):
    await interaction.response.defer(ephemeral=True)

    try:
        vc = interaction.guild.voice_client
        if vc:
            await vc.move_to(channel)
            await interaction.followup.send(f"🔁 Moved to {channel.name}", ephemeral=True)
        else:
            await channel.connect()
            await interaction.followup.send(f"✅ Joined {channel.name}", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"❌ Error: {e}", ephemeral=True)


@bot.tree.command(name="leavevc", description="Leave the current voice channel")
async def leavevc(interaction: discord.Interaction):
    vc = interaction.guild.voice_client

    if not vc:
        await interaction.response.send_message("❌ Not in VC.", ephemeral=True)
        return

    await vc.disconnect()
    await interaction.response.send_message("👋 Left VC.", ephemeral=True)


# =========================================================
# ADVANCED ANNOUNCEMENT SYSTEM
# =========================================================
COLOR_OPTIONS = [
    ("🔴 Red", "red"),
    ("🟠 Orange", "orange"),
    ("🟡 Yellow", "yellow"),
    ("🟢 Green", "green"),
    ("🔵 Blue", "blue"),
    ("🟣 Purple", "purple"),
    ("🌸 Pink", "pink"),
    ("🤍 White", "white"),
    ("🤎 Brown", "brown"),
    ("🌹 Rose", "rose"),
    ("💛 Gold", "gold"),
    ("🩵 Ice Blue", "iceblue"),
    ("💖 Magenta", "magenta"),
    ("🌑 Midnight", "midnight"),
    ("💜 Blurple", "blurple"),
    ("🎃 Pumpkin", "pumpkin"),
    ("🎨 Custom Color (enter hex)", "custom"),
]


class AnnounceCreateModal(discord.ui.Modal, title="📢 Create Announcement"):
    def __init__(self, target_channel_id: int, author_id: int):
        super().__init__(timeout=None)
        self.target_channel_id = target_channel_id
        self.author_id = author_id

        self.title_input = discord.ui.TextInput(
            label="Title",
            placeholder="Enter the announcement title...",
            max_length=256,
            required=False
        )
        self.body_input = discord.ui.TextInput(
            label="Description / Body",
            style=discord.TextStyle.paragraph,
            placeholder="Write the announcement content here...",
            max_length=4000,
            required=True
        )
        self.image_input = discord.ui.TextInput(
            label="Banner / Image URL (optional)",
            placeholder="https://example.com/banner.png",
            required=False
        )
        self.thumb_input = discord.ui.TextInput(
            label="Thumbnail URL (optional)",
            placeholder="https://example.com/icon.png",
            required=False
        )
        self.footer_input = discord.ui.TextInput(
            label="Footer Text (optional)",
            placeholder="e.g. Server Name",
            required=False
        )

        self.add_item(self.title_input)
        self.add_item(self.body_input)
        self.add_item(self.image_input)
        self.add_item(self.thumb_input)
        self.add_item(self.footer_input)

    async def on_submit(self, interaction: discord.Interaction):
        data = {
            "title": self.title_input.value.strip(),
            "message": self.body_input.value.strip(),
            "image": self.image_input.value.strip(),
            "thumbnail": self.thumb_input.value.strip(),
            "footer": self.footer_input.value.strip(),
        }

        view = AnnouncePreviewView(
            author_id=self.author_id,
            target_channel_id=self.target_channel_id,
            data=data,
            selected_color="blurple",
            custom_hex=None
        )

        preview_embed = build_announcement_embed(data, "blurple", None)

        await interaction.response.send_message(
            content="📄 **Preview — 💜 Blurple**\nClick **Send** to post or **Edit** to change.",
            embed=preview_embed,
            view=view,
            ephemeral=True
        )

        view.message = await interaction.original_response()


class AnnounceEditModal(discord.ui.Modal, title="✏️ Edit Announcement"):
    def __init__(self, preview_view):
        super().__init__(timeout=None)
        self.preview_view = preview_view
        data = preview_view.data

        self.title_input = discord.ui.TextInput(
            label="Title",
            default=data.get("title", ""),
            max_length=256,
            required=False
        )
        self.body_input = discord.ui.TextInput(
            label="Description / Body",
            style=discord.TextStyle.paragraph,
            default=data.get("message", ""),
            max_length=4000,
            required=True
        )
        self.image_input = discord.ui.TextInput(
            label="Banner / Image URL (optional)",
            default=data.get("image", ""),
            required=False
        )
        self.thumb_input = discord.ui.TextInput(
            label="Thumbnail URL (optional)",
            default=data.get("thumbnail", ""),
            required=False
        )
        self.footer_input = discord.ui.TextInput(
            label="Footer Text (optional)",
            default=data.get("footer", ""),
            required=False
        )

        self.add_item(self.title_input)
        self.add_item(self.body_input)
        self.add_item(self.image_input)
        self.add_item(self.thumb_input)
        self.add_item(self.footer_input)

    async def on_submit(self, interaction: discord.Interaction):
        self.preview_view.data = {
            "title": self.title_input.value.strip(),
            "message": self.body_input.value.strip(),
            "image": self.image_input.value.strip(),
            "thumbnail": self.thumb_input.value.strip(),
            "footer": self.footer_input.value.strip(),
        }

        await interaction.response.defer(ephemeral=True)
        await self.preview_view.refresh_message()


class CustomHexModal(discord.ui.Modal, title="🎨 Custom Color"):
    def __init__(self, preview_view):
        super().__init__(timeout=None)
        self.preview_view = preview_view
        self.hex_input = discord.ui.TextInput(
            label="HEX Color",
            placeholder="#FF0000",
            default=preview_view.custom_hex or "",
            required=True,
            max_length=7
        )
        self.add_item(self.hex_input)

    async def on_submit(self, interaction: discord.Interaction):
        value = self.hex_input.value.strip()
        if not value.startswith("#"):
            value = f"#{value}"

        try:
            int(value.replace("#", ""), 16)
        except ValueError:
            await interaction.response.send_message("❌ Invalid HEX color.", ephemeral=True)
            return

        self.preview_view.selected_color = "custom"
        self.preview_view.custom_hex = value

        await interaction.response.defer(ephemeral=True)
        await self.preview_view.refresh_message()


class ColorSelect(discord.ui.Select):
    def __init__(self):
        options = [
            discord.SelectOption(label=label, value=value, emoji=label.split()[0])
            for label, value in COLOR_OPTIONS
        ]

        super().__init__(
            placeholder="🎨 Choose a color...",
            min_values=1,
            max_values=1,
            options=options,
            row=1
        )

    async def callback(self, interaction: discord.Interaction):
        view = self.view
        if not isinstance(view, AnnouncePreviewView):
            return

        if interaction.user.id != view.author_id:
            await interaction.response.send_message("❌ This preview isn't yours.", ephemeral=True)
            return

        selected = self.values[0]

        if selected == "custom":
            await interaction.response.send_modal(CustomHexModal(view))
            return

        view.selected_color = selected
        view.custom_hex = None
        await view.update_from_component(interaction)


class AnnouncePreviewView(discord.ui.View):
    def __init__(self, author_id: int, target_channel_id: int, data: dict, selected_color: str, custom_hex: Optional[str]):
        super().__init__(timeout=600)
        self.author_id = author_id
        self.target_channel_id = target_channel_id
        self.data = data
        self.selected_color = selected_color
        self.custom_hex = custom_hex
        self.message: Optional[discord.Message] = None

        self.add_item(ColorSelect())

    def build_preview_content(self) -> str:
        return (
            f"📄 **Preview — {color_display_name(self.selected_color, self.custom_hex)}**\n"
            f"Click **Send** to post or **Edit** to change."
        )

    async def refresh_message(self):
        if not self.message:
            return

        preview_embed = build_announcement_embed(self.data, self.selected_color, self.custom_hex)
        await self.message.edit(
            content=self.build_preview_content(),
            embed=preview_embed,
            view=self
        )

    async def update_from_component(self, interaction: discord.Interaction):
        preview_embed = build_announcement_embed(self.data, self.selected_color, self.custom_hex)
        await interaction.response.edit_message(
            content=self.build_preview_content(),
            embed=preview_embed,
            view=self
        )

    @discord.ui.button(label="Send", style=discord.ButtonStyle.green, emoji="✅", row=0)
    async def send_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ This preview isn't yours.", ephemeral=True)
            return

        target_channel = interaction.guild.get_channel(self.target_channel_id)
        if not isinstance(target_channel, discord.TextChannel):
            await interaction.response.send_message("❌ Couldn't find that text channel.", ephemeral=True)
            return

        final_embed = build_announcement_embed(self.data, self.selected_color, self.custom_hex)
        await target_channel.send(embed=final_embed)

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(
            content=f"✅ Announcement sent to {target_channel.mention}",
            embed=final_embed,
            view=self
        )

    @discord.ui.button(label="Edit", style=discord.ButtonStyle.blurple, emoji="✏️", row=0)
    async def edit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ This preview isn't yours.", ephemeral=True)
            return

        await interaction.response.send_modal(AnnounceEditModal(self))

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.red, emoji="❌", row=0)
    async def cancel_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("❌ This preview isn't yours.", ephemeral=True)
            return

        for item in self.children:
            item.disabled = True

        await interaction.response.edit_message(
            content="❌ Announcement cancelled.",
            embed=None,
            view=self
        )

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.message:
            try:
                await self.message.edit(
                    content="⌛ This announcement preview expired.",
                    view=self
                )
            except Exception:
                pass


@bot.tree.command(
    name="announce",
    description="Create a fully customizable announcement embed."
)
@app_commands.describe(channel="The channel where the announcement will be posted")
@app_commands.checks.has_permissions(manage_guild=True)
async def announce(interaction: discord.Interaction, channel: discord.TextChannel):
    await interaction.response.send_modal(
        AnnounceCreateModal(
            target_channel_id=channel.id,
            author_id=interaction.user.id
        )
    )


# =========================================================
# ADMIN PANEL SUBVIEWS / MODALS
# =========================================================
class ManageUserModal(discord.ui.Modal):
    def __init__(self, action_type: str):
        super().__init__(title=f"{action_type} User")
        self.action_type = action_type

        self.user_id_input = discord.ui.TextInput(
            label="User ID",
            placeholder="Enter the user's Discord ID",
            required=True
        )
        self.extra_input = discord.ui.TextInput(
            label="Extra Value (optional)",
            placeholder="Cooldown seconds, if needed",
            required=False
        )

        self.add_item(self.user_id_input)
        self.add_item(self.extra_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            user_id = int(self.user_id_input.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
            return

        extra_value = self.extra_input.value.strip()
        message = ""

        if self.action_type == "Blacklist":
            blacklisted_users.add(user_id)
            message = f"🚫 User `{user_id}` blacklisted."

        elif self.action_type == "Whitelist":
            whitelisted_users.add(user_id)
            message = f"✅ User `{user_id}` whitelisted."

        elif self.action_type == "Unblacklist":
            blacklisted_users.discard(user_id)
            message = f"✅ User `{user_id}` removed from blacklist."

        elif self.action_type == "Unwhitelist":
            whitelisted_users.discard(user_id)
            message = f"✅ User `{user_id}` removed from whitelist."

        elif self.action_type == "Shadowban":
            shadowbanned_users.add(user_id)
            message = f"👻 User `{user_id}` shadowbanned."

        elif self.action_type == "Unshadowban":
            shadowbanned_users.discard(user_id)
            message = f"✅ User `{user_id}` unshadowbanned."

        elif self.action_type == "Cooldown":
            try:
                cooldown_seconds = int(extra_value)
                custom_cooldowns[user_id] = cooldown_seconds
                message = f"⏱ Set cooldown for `{user_id}` to `{cooldown_seconds}` second(s)."
            except ValueError:
                await interaction.response.send_message("❌ Enter a valid cooldown in seconds.", ephemeral=True)
                return

        elif self.action_type == "ClearCooldown":
            custom_cooldowns.pop(user_id, None)
            message = f"✅ Cleared custom cooldown for `{user_id}`."

        await interaction.response.send_message(message, ephemeral=True)


class UserHistoryModal(discord.ui.Modal, title="User History Lookup"):
    def __init__(self):
        super().__init__(timeout=None)
        self.user_id_input = discord.ui.TextInput(
            label="User ID",
            placeholder="Enter the user's Discord ID",
            required=True
        )
        self.add_item(self.user_id_input)

    async def on_submit(self, interaction: discord.Interaction):
        try:
            user_id = int(self.user_id_input.value.strip())
        except ValueError:
            await interaction.response.send_message("❌ Invalid user ID.", ephemeral=True)
            return

        embed = user_history_embed(user_id, interaction.guild)
        await interaction.response.send_message(embed=embed, ephemeral=True)


class LogSearchModal(discord.ui.Modal, title="Search Logs"):
    def __init__(self):
        super().__init__(timeout=None)
        self.keyword_input = discord.ui.TextInput(
            label="Keyword",
            placeholder="command, username, error, reason...",
            required=True
        )
        self.add_item(self.keyword_input)

    async def on_submit(self, interaction: discord.Interaction):
        keyword = self.keyword_input.value.strip().lower()

        results = []

        for item in command_feed:
            combined = f"{item['user_name']} {item['command']} {item['guild']}".lower()
            if keyword in combined:
                results.append(f"[CMD] {item['time'].strftime('%m-%d %I:%M %p')} | {item['user_name']} | {item['command']} | {item['guild']}")

        for item in error_feed:
            combined = f"{item['user_name']} {item['command']} {item['error']}".lower()
            if keyword in combined:
                results.append(f"[ERR] {item['time'].strftime('%m-%d %I:%M %p')} | {item['user_name']} | {item['command']} | {item['error']}")

        for user_id, logs in user_logs.items():
            for log in logs:
                combined = f"{user_id} {log['action']} {log['reason']} {log['mod']}".lower()
                if keyword in combined:
                    results.append(f"[MOD] {log['time'].strftime('%m-%d %I:%M %p')} | {user_id} | {log['action']} | {log['reason']}")

        if not results:
            await interaction.response.send_message("🔍 No matching results.", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"🔍 Search Results — {keyword}",
            color=discord.Color.blurple(),
            timestamp=get_est_time()
        )
        embed.description = "\n".join(f"`{line[:250]}`" for line in results[:12])

        await interaction.response.send_message(embed=embed, ephemeral=True)


class BotControlsView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Not for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🔒 Lock Bot", style=discord.ButtonStyle.secondary)
    async def lock_bot(self, interaction: discord.Interaction, button: discord.ui.Button):
        global bot_locked
        bot_locked = True
        add_alert("bot", "Bot was locked from the admin panel.")
        await interaction.response.send_message("🔒 Bot locked.", ephemeral=True)

    @discord.ui.button(label="🔓 Unlock Bot", style=discord.ButtonStyle.green)
    async def unlock_bot(self, interaction: discord.Interaction, button: discord.ui.Button):
        global bot_locked
        bot_locked = False
        add_alert("bot", "Bot was unlocked from the admin panel.")
        await interaction.response.send_message("🔓 Bot unlocked.", ephemeral=True)

    @discord.ui.button(label="🛑 Shutdown", style=discord.ButtonStyle.red)
    async def shutdown_bot(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("🛑 Shutting down...", ephemeral=True)
        await bot.close()


class UserControlView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Not for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🚫 Blacklist", style=discord.ButtonStyle.red, row=0)
    async def blacklist_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ManageUserModal("Blacklist"))

    @discord.ui.button(label="✅ Whitelist", style=discord.ButtonStyle.green, row=0)
    async def whitelist_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ManageUserModal("Whitelist"))

    @discord.ui.button(label="➖ Unblacklist", style=discord.ButtonStyle.secondary, row=0)
    async def unblacklist_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ManageUserModal("Unblacklist"))

    @discord.ui.button(label="➖ Unwhitelist", style=discord.ButtonStyle.secondary, row=0)
    async def unwhitelist_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ManageUserModal("Unwhitelist"))

    @discord.ui.button(label="👻 Shadowban", style=discord.ButtonStyle.red, row=1)
    async def shadowban_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ManageUserModal("Shadowban"))

    @discord.ui.button(label="🌤 Unshadowban", style=discord.ButtonStyle.green, row=1)
    async def unshadowban_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ManageUserModal("Unshadowban"))

    @discord.ui.button(label="⏱ Set Cooldown", style=discord.ButtonStyle.blurple, row=1)
    async def cooldown_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ManageUserModal("Cooldown"))

    @discord.ui.button(label="🧹 Clear Cooldown", style=discord.ButtonStyle.secondary, row=1)
    async def clear_cooldown_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ManageUserModal("ClearCooldown"))

    @discord.ui.button(label="📜 User History", style=discord.ButtonStyle.blurple, row=2)
    async def user_history_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(UserHistoryModal())


class LogExplorerView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Not for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="🔍 Search Logs", style=discord.ButtonStyle.blurple)
    async def search_logs_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LogSearchModal())

    @discord.ui.button(label="📤 Export Logs", style=discord.ButtonStyle.green)
    async def export_logs_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        lines = []
        lines.append("=== COMMAND FEED ===")
        for x in command_feed:
            lines.append(
                f"{x['time'].strftime('%Y-%m-%d %I:%M %p %Z')} | {x['user_name']} ({x['user_id']}) | {x['command']} | {x['guild']}"
            )

        lines.append("\n=== ERROR FEED ===")
        for x in error_feed:
            lines.append(
                f"{x['time'].strftime('%Y-%m-%d %I:%M %p %Z')} | {x['user_name']} ({x['user_id']}) | {x['command']} | {x['error']}"
            )

        lines.append("\n=== MOD LOGS ===")
        for uid, logs in user_logs.items():
            for log in logs:
                lines.append(
                    f"{log['time'].strftime('%Y-%m-%d %I:%M %p %Z')} | user:{uid} | {log['action']} | {log['reason']} | mod:{log['mod']}"
                )

        file_bytes = io.BytesIO("\n".join(lines).encode("utf-8"))
        discord_file = discord.File(file_bytes, filename="bot_logs_export.txt")
        await interaction.response.send_message("📤 Exported logs:", file=discord_file, ephemeral=True)


class AdminPanelMainView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=600)

    async def interaction_check(self, interaction: discord.Interaction):
        if interaction.user.id != OWNER_ID:
            await interaction.response.send_message("❌ Not for you.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="📡 Live Feed", style=discord.ButtonStyle.blurple, row=0)
    async def live_feed_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="📡 Live Command Feed",
            color=discord.Color.green(),
            timestamp=get_est_time()
        )

        if not command_feed:
            embed.description = "No commands logged yet."
        else:
            lines = []
            for item in reversed(command_feed[-12:]):
                lines.append(
                    f"`{item['time'].strftime('%I:%M %p')}` **{item['command']}** — {item['user_name']} in {item['guild']}"
                )
            embed.description = "\n".join(lines)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="👤 User Control", style=discord.ButtonStyle.blurple, row=0)
    async def user_control_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="👤 User Control Panel",
            description="Manage blacklist, whitelist, shadowban, cooldowns, and user history.",
            color=discord.Color.blurple(),
            timestamp=get_est_time()
        )
        await interaction.response.send_message(embed=embed, view=UserControlView(), ephemeral=True)

    @discord.ui.button(label="📊 Analytics", style=discord.ButtonStyle.blurple, row=0)
    async def analytics_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="📊 Analytics Dashboard",
            color=discord.Color.blue(),
            timestamp=get_est_time()
        )

        top_commands = command_usage.most_common(8)
        if top_commands:
            embed.add_field(
                name="Most Used Commands",
                value="\n".join(f"`{name}` — {count}" for name, count in top_commands),
                inline=False
            )
        else:
            embed.add_field(name="Most Used Commands", value="No data yet.", inline=False)

        today = get_est_time().strftime("%Y-%m-%d")
        active_today = len(daily_active_users.get(today, set()))
        embed.add_field(name="Active Users Today", value=str(active_today), inline=True)
        embed.add_field(name="Total Errors Logged", value=str(len(error_feed)), inline=True)
        embed.add_field(name="Tracked Servers", value=str(len(bot.guilds)), inline=True)

        growth_lines = []
        for guild in bot.guilds[:10]:
            current = guild.member_count or 0
            previous = server_member_snapshots.get(guild.id, current)
            diff = current - previous
            growth_lines.append(f"{guild.name}: {current} ({diff:+})")
            server_member_snapshots[guild.id] = current

        embed.add_field(
            name="Server Growth Snapshot",
            value="\n".join(growth_lines) if growth_lines else "No server data.",
            inline=False
        )

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="🚨 Alerts", style=discord.ButtonStyle.red, row=1)
    async def alerts_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🚨 Alert System",
            color=discord.Color.red(),
            timestamp=get_est_time()
        )

        if not alerts_feed:
            embed.description = "No alerts right now."
        else:
            lines = []
            for item in reversed(alerts_feed[-12:]):
                lines.append(
                    f"`{item['time'].strftime('%I:%M %p')}` [{item['kind'].upper()}] {item['message']}"
                )
            embed.description = "\n".join(lines)

        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="🧾 Log Explorer", style=discord.ButtonStyle.green, row=1)
    async def log_explorer_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="🧾 Log Explorer",
            description="Search across command logs, error logs, and mod logs or export them.",
            color=discord.Color.green(),
            timestamp=get_est_time()
        )
        await interaction.response.send_message(embed=embed, view=LogExplorerView(), ephemeral=True)

    @discord.ui.button(label="⚙️ Bot Controls", style=discord.ButtonStyle.secondary, row=1)
    async def bot_controls_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        embed = discord.Embed(
            title="⚙️ Bot Controls",
            description="Lock, unlock, or shut down the bot.",
            color=discord.Color.orange(),
            timestamp=get_est_time()
        )
        await interaction.response.send_message(embed=embed, view=BotControlsView(), ephemeral=True)


# =========================================================
# SECRET ADMIN PANEL COMMAND
# =========================================================
@bot.command()
async def adminpanel(ctx, code: str):
    if ctx.author.id != OWNER_ID:
        return await ctx.send("❌ Not allowed.")

    if code != SECRET_CODE:
        return await ctx.send("❌ Wrong code.")

    try:
        await ctx.message.delete()
    except Exception:
        pass

    embed = discord.Embed(
        title="🛑 Admin Panel",
        description=(
            "Private control panel\n\n"
            "Use the buttons below to open:\n"
            "• Live Command Feed\n"
            "• User Control Panel\n"
            "• Analytics Dashboard\n"
            "• Alert System\n"
            "• Log Explorer\n"
            "• Bot Controls"
        ),
        color=discord.Color.red(),
        timestamp=get_est_time()
    )

    await ctx.author.send(embed=embed, view=AdminPanelMainView())


# =========================================================
# ERROR HANDLERS
# =========================================================
@announce.error
async def announce_error(interaction: discord.Interaction, error):
    if isinstance(error, app_commands.MissingPermissions):
        if interaction.response.is_done():
            await interaction.followup.send("❌ You need Manage Server to use this.", ephemeral=True)
        else:
            await interaction.response.send_message("❌ You need Manage Server to use this.", ephemeral=True)
        return

    log_error_entry(
        user_name=str(interaction.user),
        user_id=interaction.user.id,
        command_name="/announce",
        error_text=str(error)
    )

    if interaction.response.is_done():
        await interaction.followup.send(f"❌ Error: {error}", ephemeral=True)
    else:
        await interaction.response.send_message(f"❌ Error: {error}", ephemeral=True)


@bot.event
async def on_command_error(ctx, error):
    command_name = ctx.command.name if ctx.command else "unknown"
    log_error_entry(
        user_name=str(ctx.author),
        user_id=ctx.author.id,
        command_name=command_name,
        error_text=str(error)
    )

    if isinstance(error, commands.MissingPermissions):
        await ctx.send("❌ You don't have permission to use this.")
    elif isinstance(error, commands.MissingRequiredArgument):
        await ctx.send("❌ Missing required arguments.")
    elif isinstance(error, commands.CheckFailure):
        # silent for shadowban / blacklist / cooldown / lock
        pass
    else:
        await ctx.send(f"❌ Error: {error}")


# =========================================================
# RUN
# =========================================================
bot.run(os.getenv("DISCORD_TOKEN"))
