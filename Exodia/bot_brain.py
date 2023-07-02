#imports
import win32gui
import bot_env as screen

# The bot brain handles knowing information pertinent to the bot functioning
# Currently it handles finding RuneLite's PID, tesseract path, client location/dimensions
class BotBrain():

    def __init__(self, DEBUG=False):
        self.id = -1
        self.runelite = 'RuneLite'
        # Client dimensions on the monitor
        self.win_rect = []

        # Debug flag, bot_brain(true) will show images of each step being performed
        self._DEBUG = DEBUG

        # Bot needs this information before it can be ran
        self._find_window()


    # Update function for the brain, updates the location of the client dimensions
    def update(self):
        self.get_window_rect()


    def _find_window(self):  # find window name returns PID of the window, needs to be run first to establish the PID
        win32gui.EnumWindows(self.enum_window_callback, None)
        if self.id != None:
            self.get_window_rect()
            # win32gui.SetActiveWindow(winiD)
            if self._DEBUG:
                print('Window handle: %i'%(self.id))
                print('Window rect: ', self.win_rect)
                screen.debug_view(screen.block_name(screen.screen_image(self.win_rect)), title='Find window ID debug')
        else:
            raise RuneLiteNotFoundException('RuneLite cannot be found!')


    #Callback function for EnumWindows, once it finds the window its looking for, sets the global to the PID
    def enum_window_callback(self, hwnd, extra):
        if 'RuneLite' in win32gui.GetWindowText(hwnd) and win32gui.IsWindowVisible(hwnd):
            self.id = hwnd


    # Returns left, right, top, bottom
    def get_window_rect(self):
        rect = win32gui.GetWindowRect(self.id)
        self.win_rect = [rect[0], rect[1], rect[2]-rect[0], rect[3]-rect[1]]
        if(self._DEBUG):
            print('GET WINDOW RECT: ', self.win_rect)
            image = screen.screen_image(self.win_rect)
            screen.debug_view(image, title='BotBrain Debug get_window_rect')
        # If the window isnt on the main monitor we need to move it so everything can work- not implemented


# Exception to throw when the bot is constructed while RuneLite isnt open
class RuneLiteNotFoundException(Exception):
    pass