import discord
from redbot.core import commands, Config, checks
from redbot.core.bot import Red
from mistralai import Mistral
from typing import Optional, List
import asyncio
from collections import deque

class AdaptiveAI(commands.Cog):
“”“An adaptive AI chat cog that learns from server slang”””

```
def __init__(self, bot: Red):
    self.bot = bot
    self.config = Config.get_conf(self, identifier=1234567890, force_registration=True)
    
    default_guild = {
        "freeroom_channel": None,
        "api_keys": [],  # List of up to 8 API keys
        "current_key_index": 0  # Which key is currently being used
    }
    
    self.config.register_guild(**default_guild)
    
    # Storage for last 50 messages per channel
    self.message_history = {}
    
async def get_api_keys(self, guild: discord.Guild) -> List[str]:
    """Gets all API keys for the guild"""
    return await self.config.guild(guild).api_keys()

async def get_current_api_key(self, guild: discord.Guild) -> Optional[str]:
    """Gets the currently active API key"""
    keys = await self.get_api_keys(guild)
    if not keys:
        return None
    
    current_index = await self.config.guild(guild).current_key_index()
    
    # Ensure index is valid
    if current_index >= len(keys):
        current_index = 0
        await self.config.guild(guild).current_key_index.set(0)
    
    return keys[current_index]

async def switch_to_next_key(self, guild: discord.Guild) -> bool:
    """Switches to next API key, returns True if successful"""
    keys = await self.get_api_keys(guild)
    if len(keys) <= 1:
        return False
    
    current_index = await self.config.guild(guild).current_key_index()
    next_index = (current_index + 1) % len(keys)
    
    await self.config.guild(guild).current_key_index.set(next_index)
    return True

def add_message_to_history(self, channel_id: int, author: str, content: str):
    """Adds a message to history (max 50 per channel)"""
    if channel_id not in self.message_history:
        self.message_history[channel_id] = deque(maxlen=50)
    
    self.message_history[channel_id].append(f"{author}: {content}")

def get_channel_context(self, channel_id: int) -> str:
    """Creates context from recent messages"""
    if channel_id not in self.message_history:
        return "No previous messages available."
    
    messages = list(self.message_history[channel_id])
    return "\n".join(messages[-30:])  # Last 30 messages for context

async def generate_response(self, guild: discord.Guild, channel_id: int, user_message: str, author_name: str) -> str:
    """Generates an AI response based on server context"""
    api_key = await self.get_current_api_key(guild)
    
    if not api_key:
        return "❌ No API key configured! Use `/aiaddkey` to set one up."
    
    max_retries = await self.config.guild(guild).api_keys()
    retry_count = 0
    
    while retry_count < len(max_retries):
        try:
            client = Mistral(api_key=api_key)
            
            # Bot Owner Info
            owner = self.bot.get_user(self.bot.owner_id)
            owner_name = str(owner) if owner else "Unknown"
            
            # Context from chat history
            chat_context = self.get_channel_context(channel_id)
            
            # System Prompt
            system_prompt = f"""You are a Discord bot on a server and you adapt to the server slang.
```

IMPORTANT RULES:

- Learn from the users’ chat style and adapt to it
- Use similar expressions, emojis, and slang as the users
- Don’t write too long messages (1-3 sentences are ideal)
- Be authentic and natural
- If asked about the bot owner: The owner is {owner_name}

CHAT CONTEXT (recent messages):
{chat_context}

Analyze the writing style and respond in the same style.”””

```
            response = client.chat.complete(
                model="mistral-large-latest",
                messages=[
                    {
                        "role": "system",
                        "content": system_prompt
                    },
                    {
                        "role": "user",
                        "content": f"{author_name} asks: {user_message}"
                    }
                ],
                max_tokens=300
            )
            
            return response.choices[0].message.content
            
        except Exception as e:
            error_msg = str(e).lower()
            
            # Switch to next key on rate limit or API error
            if "rate" in error_msg or "limit" in error_msg or "quota" in error_msg:
                switched = await self.switch_to_next_key(guild)
                if switched:
                    api_key = await self.get_current_api_key(guild)
                    retry_count += 1
                    continue
            
            # Break on other errors
            return f"❌ Error generating AI response: {str(e)}"
    
    return "❌ All API keys have reached their limit. Please try again later."

@commands.Cog.listener()
async def on_message(self, message: discord.Message):
    """Listener for all messages"""
    # Ignore bot messages
    if message.author.bot:
        return
    
    # Ignore messages without guild
    if not message.guild:
        return
    
    # Save message to history
    self.add_message_to_history(
        message.channel.id,
        message.author.display_name,
        message.content
    )
    
    # Check if freeroom channel
    freeroom_id = await self.config.guild(message.guild).freeroom_channel()
    
    if freeroom_id and message.channel.id == freeroom_id:
        # Reply to every message in freeroom
        async with message.channel.typing():
            response = await self.generate_response(
                message.guild,
                message.channel.id,
                message.content,
                message.author.display_name
            )
            await message.channel.send(response)
    
    # Check if bot was mentioned
    elif self.bot.user in message.mentions:
        # Remove mention from message
        content = message.content.replace(f'<@{self.bot.user.id}>', '').strip()
        content = content.replace(f'<@!{self.bot.user.id}>', '').strip()
        
        if content:
            async with message.channel.typing():
                response = await self.generate_response(
                    message.guild,
                    message.channel.id,
                    content,
                    message.author.display_name
                )
                await message.reply(response)

@commands.hybrid_command(name="aisetfreeroom")
@checks.admin_or_permissions(manage_guild=True)
async def set_freeroom(self, ctx: commands.Context, channel: discord.TextChannel):
    """Sets the free-room channel where the bot responds to everything
    
    Example: /aisetfreeroom #ai-chat
    """
    await self.config.guild(ctx.guild).freeroom_channel.set(channel.id)
    await ctx.send(f"✅ Free-room channel has been set to {channel.mention}!\n"
                  f"The bot will now respond to every message in this channel.")

@commands.hybrid_command(name="airemovefreeroom")
@checks.admin_or_permissions(manage_guild=True)
async def remove_freeroom(self, ctx: commands.Context):
    """Removes the free-room channel"""
    await self.config.guild(ctx.guild).freeroom_channel.set(None)
    await ctx.send("✅ Free-room channel has been removed!")

@commands.hybrid_command(name="aiaddkey")
@checks.is_owner()
async def add_api_key(self, ctx: commands.Context, api_key: str):
    """Adds a Mistral API key (max. 8 keys)
    
    IMPORTANT: Run this command in DM, not publicly!
    """
    keys = await self.get_api_keys(ctx.guild)
    
    if len(keys) >= 8:
        await ctx.send("❌ Maximum of 8 API keys reached!", ephemeral=True)
        return
    
    if api_key in keys:
        await ctx.send("❌ This API key is already added!", ephemeral=True)
        return
    
    keys.append(api_key)
    await self.config.guild(ctx.guild).api_keys.set(keys)
    
    # Delete message with key
    try:
        await ctx.message.delete()
    except:
        pass
    
    await ctx.send(f"✅ API key #{len(keys)} has been added! (Total: {len(keys)}/8)", ephemeral=True)

@commands.hybrid_command(name="airemovekey")
@checks.is_owner()
async def remove_api_key(self, ctx: commands.Context, key_number: int):
    """Removes an API key by number (1-8)
    
    Example: /airemovekey 3
    """
    keys = await self.get_api_keys(ctx.guild)
    
    if key_number < 1 or key_number > len(keys):
        await ctx.send(f"❌ Invalid key number! (1-{len(keys)})", ephemeral=True)
        return
    
    removed_key = keys.pop(key_number - 1)
    await self.config.guild(ctx.guild).api_keys.set(keys)
    
    # Reset index if necessary
    current_index = await self.config.guild(ctx.guild).current_key_index()
    if current_index >= len(keys) and len(keys) > 0:
        await self.config.guild(ctx.guild).current_key_index.set(0)
    
    await ctx.send(f"✅ API key #{key_number} has been removed! (Remaining: {len(keys)})", ephemeral=True)

@commands.hybrid_command(name="ailistkeys")
@checks.is_owner()
async def list_api_keys(self, ctx: commands.Context):
    """Shows all saved API keys (masked)"""
    keys = await self.get_api_keys(ctx.guild)
    current_index = await self.config.guild(ctx.guild).current_key_index()
    
    if not keys:
        await ctx.send("❌ No API keys configured!", ephemeral=True)
        return
    
    embed = discord.Embed(
        title="🔑 API Keys Overview",
        description=f"Total: {len(keys)}/8 Keys",
        color=discord.Color.blue()
    )
    
    for i, key in enumerate(keys, 1):
        # Show only last 4 characters
        masked_key = f"...{key[-4:]}" if len(key) > 4 else "****"
        status = "🟢 ACTIVE" if i - 1 == current_index else "⚪"
        embed.add_field(
            name=f"Key #{i} {status}",
            value=f"`{masked_key}`",
            inline=True
        )
    
    await ctx.send(embed=embed, ephemeral=True)

@commands.hybrid_command(name="aiswitchkey")
@checks.is_owner()
async def switch_key(self, ctx: commands.Context):
    """Manually switches to next API key"""
    switched = await self.switch_to_next_key(ctx.guild)
    
    if switched:
        current_index = await self.config.guild(ctx.guild).current_key_index()
        await ctx.send(f"✅ Switched to API key #{current_index + 1}", ephemeral=True)
    else:
        await ctx.send("❌ Only one API key available, cannot switch!", ephemeral=True)

@commands.hybrid_command(name="aiclear")
@checks.admin_or_permissions(manage_messages=True)
async def clear_history(self, ctx: commands.Context):
    """Clears the saved message history for this channel"""
    if ctx.channel.id in self.message_history:
        del self.message_history[ctx.channel.id]
        await ctx.send("✅ Message history for this channel has been cleared!")
    else:
        await ctx.send("ℹ️ No history available for this channel.")

@commands.hybrid_command(name="aiinfo")
async def ai_info(self, ctx: commands.Context):
    """Shows information about the AI bot"""
    freeroom_id = await self.config.guild(ctx.guild).freeroom_channel()
    freeroom_channel = ctx.guild.get_channel(freeroom_id) if freeroom_id else None
    
    owner = self.bot.get_user(self.bot.owner_id)
    owner_name = str(owner) if owner else "Unknown"
    
    keys = await self.get_api_keys(ctx.guild)
    
    embed = discord.Embed(
        title="🤖 Adaptive AI Bot Info",
        color=discord.Color.blue()
    )
    
    embed.add_field(
        name="Bot Owner",
        value=f"{owner_name}",
        inline=False
    )
    
    embed.add_field(
        name="Free-Room Channel",
        value=freeroom_channel.mention if freeroom_channel else "Not configured",
        inline=False
    )
    
    embed.add_field(
        name="API Keys",
        value=f"{len(keys)}/8 keys configured",
        inline=False
    )
    
    embed.add_field(
        name="AI Model",
        value="Mistral AI (mistral-large-latest)",
        inline=False
    )
    
    embed.add_field(
        name="How does the bot work?",
        value="• Mention the bot (@Bot) for a response\n"
              "• In free-room it responds to every message\n"
              "• It learns from the last 50 messages in the channel\n"
              "• It adapts to the server slang\n"
              "• Automatic switch on API limits",
        inline=False
    )
    
    await ctx.send(embed=embed)
```

async def setup(bot: Red):
“”“Setup function for the cog”””
await bot.add_cog(AdaptiveAI(bot))
