import time
from urllib.request import urlopen, Request
import json
from dateutil import tz, parser as dateparser
from fake_useragent import UserAgent
from pyaib.plugins import every, keyword, plugin_class
from fbbot.thirdparty.ircformat import bold, underline

#Constants
MODE_ACTIVE = 0
MODE_INACTIVE = 1
GAME_STATUS_PRE = 0
GAME_STATUS_IN = 1
GAME_STATUS_POST = 2

def convertDateToEastern(date):
    to_zone = tz.gettz('America/New_York')
    utc = dateparser.parse(date)
    eastern = utc.astimezone(to_zone)
    return eastern.strftime('%A, %B %d, %I:%M %p %Z')

@plugin_class
class CFBScores:

    def __init__(self, irc_context, config):
        self.config = config
        print(self.config)
        self.ua = UserAgent().chrome
        self.lastUpdate = 0
        self.mode = MODE_ACTIVE
        self.fbs = {}

    def ircLog(self, irc_c, msg):
        print("cfbscores: " + msg)
        irc_c.PRIVMSG(self.config.debug_chan, msg)

    @every(10, "scoreupdate")
    def updateScores(self, irc_c, event):
        curTime = time.time()
        if self.mode == MODE_INACTIVE:
            if curTime - self.lastUpdate < self.config.inactive_freq:
                print("updateScores: Inactive mode, waiting")
                return

        newData = {}
        try:
            print("Updating FBS score data...")
            newData = self.getGames("fbs")
        except Exception as ex:
            self.ircLog(irc_c, "Error retrieving scores: " + str(ex))
            self.lastUpdate = curTime

        activeGames = False
        for gameID in newData.keys():
            newGame = newData[gameID]
            if newGame['status'] == GAME_STATUS_IN:
                # One game is active, at least
                activeGames = True
            if gameID not in self.fbs:
                # New game - if active, send status
                #if newGame['status'] == GAME_STATUS_IN:
                #    self.announceScore(irc_c, newGame)
                continue
            oldGame = self.fbs[gameID]

            # Check for state change
            if newGame['status'] != oldGame['status']:
                if newGame['status'] == GAME_STATUS_IN:
                    self.announceScore(irc_c, newGame, prefix="Game Started: ")
                elif newGame['status'] == GAME_STATUS_POST:
                    self.announceScore(irc_c, newGame, prefix="Game Ended: ")
                continue

            # Halftime
            if newGame['time'] == "Halftime" and newGame['time'] != oldGame['time']:
                self.announceScore(irc_c, newGame)
            # After halftime
            if oldGame['time'] == "Halftime" and newGame['time'] != oldGame['time']:
                self.announceScore(irc_c, newGame)

            if newGame['status'] == GAME_STATUS_IN:
                chgHome = newGame['homescore'] - oldGame['homescore']
                chgAway = newGame['awayscore'] - oldGame['awayscore']
                if chgHome > 0 or chgAway > 0:
                    self.announceScore(irc_c, newGame, chgHome, chgAway)

        self.fbs = newData
        if activeGames and self.mode == MODE_INACTIVE:
            self.ircLog(irc_c, "At least one game is active, enabling active mode.")
            self.mode = MODE_ACTIVE
        elif not activeGames and self.mode == MODE_ACTIVE:
            self.ircLog(irc_c, "All games are inactive, disabling active mode.")
            self.mode = MODE_INACTIVE

        self.lastUpdate = curTime


    def getScoringDesc(self, change):
        if change == 1:
            return "extra point GOOD"
        elif change == 2:
            return "2-point conversion GOOD"
        elif change == 3:
            return "FIELD GOAL"
        elif change == 6:
            return "TOUCHDOWN!"
        elif change == 7:
            return "TOUCHDOWN! (+XP)"
        else:
            return None

    @keyword("score")
    def score(self, irc_c, msg, trigger, args, kargs):
        team = ' '.join(args).lower()
        for gameid, game in self.fbs.items():
            if team == game['hometeam'].lower() or \
                 team == game['awayteam'].lower():
                msg.reply(self.getLongGameDesc(game))

    @keyword("whatson")
    def whatson(self, irc_c, msg, trigger, args, kargs):
        reply = "Games on TV: "
        first = True
        for gameid, game in self.fbs.items():
            if game['status'] == GAME_STATUS_IN and "network" in game:
                if first:
                    first = False
                else:
                    reply += " | "
                reply += self.getShortGameDesc(game)
        irc_c.PRIVMSG(msg.sender.nick, reply)

    @keyword("closegames")
    def closegames(self, irc_c, msg, trigger, args, kargs):
        reply = "Close Games: "
        first = True
        for gameid, game in self.fbs.items():
            diff = abs(game['homescore'] - game['awayscore'])
            if game['status'] == GAME_STATUS_IN and diff <= 10:
                if first:
                    first = False
                else:
                    reply += " | "
                reply += self.getShortGameDesc(game)
        irc_c.PRIVMSG(msg.sender.nick, reply)

    def announceScore(self, irc_c, game, chgHome = 0, chgAway = 0, prefix = ""):
        msg = prefix + self.getLongGameDesc(game, chgHome, chgAway)
        print("Score announcement: " + msg)
        for channel in self.config.live_chans:
            irc_c.PRIVMSG(channel, msg)

    def getShortGameDesc(self, game):
        if game['status'] == GAME_STATUS_PRE:
            output = "%s @ %s - %s" % (game['awayabv'], game['homeabv'],
                                       game['time'])
            if "network" in game:
                output += " (%s)" % game['network']
            return output
        elif game['status'] == GAME_STATUS_IN:
            output = "%s %d @ %s %d - %s" % (game['awayabv'], game['awayscore'],
                                             game['homeabv'], game['homescore'],
                                             game['time'])
            if "network" in game:
                output += " (%s)" % game['network']
            return output
        else:
            output = "%s %d @ %s %d - %s" % (game['awayabv'], game['awayscore'],
                                             game['homeabv'], game['homescore'],
                                             game['time'])
            return output

    def getLongGameDesc(self, game, chgHome = 0, chgAway = 0):
        output = ""
        if game['status'] == GAME_STATUS_PRE:
            output += "%s @ %s - %s - %s" % (bold(game['awayteam']), bold(game['hometeam']),
                                            convertDateToEastern(game['date']),
                                            game['location'])
            if "network" in game:
                output += " [TV: %s]" % game['network']
        elif game['status'] == GAME_STATUS_POST:
            output += "%s %d @ %s %d - FINAL" % (bold(game['awayteam']), game['awayscore'],
                                                 bold(game['hometeam']), game['homescore'])
        elif game['status'] == GAME_STATUS_IN:
            output += "%s %d" % (bold(game['awayteam']), game['awayscore'])
            if "possess" in game and game['possess'] == "home":
                output += " <-"
            output += " @"
            if "possess" in game and game['possess'] == "away":
                output += " ->"
            output += " %s %d" % (bold(game['hometeam']), game['homescore'])

            output += " - %s" % game['time']

            if chgHome > 0 and chgAway == 0:
                sDesc = self.getScoringDesc(chgHome)
                if sDesc is not None:
                    output += " | %s" % underline(game['hometeam'] + " " + sDesc)
            if chgHome == 0 and chgAway > 0:
                sDesc = self.getScoringDesc(chgAway)
                if sDesc is not None:
                    output += " - %s" % underline(game['awayteam'] + " " + sDesc)

            elif chgHome == 0 and chgAway == 0:
                if "down" in game:
                    output += " | %s" % game['down']
                if "lastplay" in game and game['time'] != "Halftime":
                    output += " (Last play: %s)" % game['lastplay']

            if "network" in game:
                output += " [TV: %s]" % game['network']

        return output

#    def getGames(self, league="fbs"):
#        with open('data.json') as data_file:
#            return json.load(data_file)

    # Primary magic happens here
    def getGames(self, league="fbs"):
        type = "80" # 80 = FBS
        if league == "fcs":
            type = "81"
        # Other leagues go here

        req = Request("http://espn.go.com/college-football/scoreboard/_/group/" +
                      type + "/year/2016/seasontype/2/?t=" + str(time.time()))
        req.headers["User-Agent"] = self.ua
        # Load data
        scoreData = urlopen(req).read().decode("utf-8")
        scoreData = scoreData[scoreData.find('window.espn.scoreboardData 	= ')+len('window.espn.scoreboardData 	= '):]
        scoreData = json.loads(scoreData[:scoreData.find('};')+1])

        games = dict()

        for event in scoreData['events']:
            game = dict()

            game["date"] = event['date']
            status = event['status']['type']['state']
            if status == "pre":
                game['status'] = GAME_STATUS_PRE
            elif status == "in":
                game['status'] = GAME_STATUS_IN
            else:
                game['status'] = GAME_STATUS_POST
            team1 = event['competitions'][0]['competitors'][0]['team']['location']
            tid1 = event['competitions'][0]['competitors'][0]['id']
            score1 = int(event['competitions'][0]['competitors'][0]['score'])
            team1abv = event['competitions'][0]['competitors'][0]['team']['abbreviation']
            team2 = event['competitions'][0]['competitors'][1]['team']['location']
            tid2 = event['competitions'][0]['competitors'][1]['id']
            score2 = int(event['competitions'][0]['competitors'][1]['score'])
            team2abv = event['competitions'][0]['competitors'][1]['team']['abbreviation']

            homestatus = event['competitions'][0]['competitors'][0]['homeAway']

            if homestatus == 'home':
                game['hometeam'], game['homeid'], game['homeabv'], game['homescore'], game['awayteam'], game['awayid'], game['awayabv'], game['awayscore'] =\
                    team1, tid1, team1abv, score1, team2, tid2, team2abv, score2
            else:
                game['hometeam'], game['homeid'], game['homeabv'], game['homescore'], game['awayteam'], game['awayid'], game['awayabv'], game['awayscore'] = \
                    team2, tid2, team2abv, score2, team1, tid1, team1abv, score1

            game['time'] = event['status']['type']['shortDetail']
            try:
                game['network'] = event['competitions'][0]['broadcasts'][0]['names'][0]
            except:
                pass
            try:
                game['down'] = event['competitions'][0]['situation']['downDistanceText']
            except:
                pass
            try:
                possessor = event['competitions'][0]['situation']['possession']
                if possessor == game['awayid']:
                    game['possess'] = "away"
                else:
                    game['possess'] = "home"
            except:
                pass
            try:
                game['lastplay'] = event['competitions'][0]['situation']['lastPlay']['text']
            except:
                pass
            game['location'] = event['competitions'][0]['venue']['address']['city']
            try:
                game['location'] += ", " + event['competitions'][0]['venue']['address']['state']
            except:
                pass

            gid = event['id']
            games[gid] = game
        return games
