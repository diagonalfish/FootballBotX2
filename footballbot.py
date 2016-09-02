from pyaib.ircbot import IrcBot
import sys

argv = sys.argv[1:]

bot = IrcBot(argv[0] if argv else 'footballbot.conf')

print("Config Dump: %s" % bot.config)

#Bot Take over
bot.run()
