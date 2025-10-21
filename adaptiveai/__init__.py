from .adaptiveai import AdaptiveAI

async def setup(bot):
    await bot.add_cog(AdaptiveAI(bot))
