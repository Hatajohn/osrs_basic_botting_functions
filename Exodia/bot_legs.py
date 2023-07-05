# Imports
import time

# Handles the runtime of the bot session
class BotLegs():
    # Constructor
    def __init__(self, mods=[], DEBUG=False):
        self._DEBUG = DEBUG
        self._mods = mods
        self.flag = False

        # Time period for updates, each game tick is 0.6 seconds but it probably isnt practical 
        # to try to sync the bot with the game w/o some sort of reading of the game client info
        self._t = 6000

        # Max amount of time (ms) that I want the bot to be running
        self._max = 600000

        # The queue for tasks the bot needs to perform on the next cycle
        self.to_do = []


    # Run update on each bot object
    def update_all(self):
        # Updates in each object in order
        for m in self._mods:
            # Try to call the update function on each object legs needs to update per cycle
            if hasattr(m, 'update') and callable(getattr(m, 'update')):
                try: 
                    m.update()
                except:
                    print('Object could not be updated!')
                    # Stop the session
                    self.flag = True
                    break
            else:
                print('Object does not have a function called update()')

    
    # Add a task for the bot to do to the queue
    def add_task(self, object=None, func='', params=[]):
        self.to_do.append(Task(object, func, params))


    # Will run each command passed to the list, in order
    def run_tasks(self):
        for task in self.to_do:
            task.run()


    # Updates the bot every _t seconds
    def bot_loop(self):
        self.update_all()
        end = 0
        last_time = time.time()
        delta_time = 0
        # Something else needs to stop this
        while(end > self._max):
            curr_time = time.time()
            # If we have passed the time period, we need to update each object legs is watching
            if delta_time > self._t:
                self.update_all()
                self.run_tasks()
                last_time = time.time()
            end += time.time() - last_time
            delta_time += curr_time - last_time
            print(end)



# A class for tasks the bot will need to perform
class Task():
    # Constructor
    def __init__(self, object=None, func='', params=[]):
        # The object that needs to run the function
        self._object = object
        # The function-string that will be called when run() is called
        self._func = func
        # Parameters for the function call
        self._params = params


    # Run this task
    def run(self):
        try:
            if self._object != None:
                func = self._func
                has_attr = hasattr(self._object, self._func)
                is_callable = callable(getattr(self._object, self._func))
                if has_attr and is_callable:
                    self._object.func(self._params)
            else:
                self._func(self._params)
        except:
            raise Exception('Task could not be run! ' + self._func)