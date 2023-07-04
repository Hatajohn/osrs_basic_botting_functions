# A class to handle the bot's inventory
# Imports

# I likely do not need this class but I'm keeping it around in case I change my mind
class BotBag():
    def __init__(self) -> None:
        # Inventory dimensions
        w,h = 4, 7

        # Bag is 4x7
        self.bag = [[None for x in range(w)] for y in range(h)]