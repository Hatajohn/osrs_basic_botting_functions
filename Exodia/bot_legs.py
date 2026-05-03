# Imports
import time

# Handles the runtime of the bot session.
# ``_t`` is milliseconds between ``update_all`` / ``run_tasks`` cycles (default 6000).
# For OSRS tick ~0.6s use e.g. ``600`` or import ``Env.PERF_TICK_S`` and set ``_t = int(Env.PERF_TICK_S * 1000)``.
class BotLegs():
    # Constructor
    def __init__(self, mods=None, DEBUG=False):
        if mods is None:
            mods = []
        self._DEBUG = DEBUG
        self._mods = mods
        self.flag = False

        self._t = 6000

        self._max = 600000

        self.to_do = []

    def update_all(self):
        for m in self._mods:
            if hasattr(m, "update") and callable(getattr(m, "update")):
                try:
                    m.update()
                except Exception as e:
                    print("Object could not be updated: %s" % (repr(e),))
                    self.flag = True
                    break
            else:
                print("Object does not have a function called update()")

    def add_task(self, object=None, func='', params=None):
        if params is None:
            params = []
        self.to_do.append(Task(object, func, params))

    def run_tasks(self):
        for task in self.to_do:
            task.run()

    def bot_loop(self):
        """
        Runs until elapsed wall time exceeds ``_max`` (ms) or ``self.flag`` is set.
        Each cycle waits at least ``_t`` ms since the previous ``update_all``.
        """
        self.update_all()
        start = time.monotonic()
        last_cycle = start
        while True:
            if self.flag:
                break
            elapsed_ms = (time.monotonic() - start) * 1000.0
            if elapsed_ms >= self._max:
                break
            now = time.monotonic()
            since_last_ms = (now - last_cycle) * 1000.0
            if since_last_ms >= self._t:
                self.update_all()
                self.run_tasks()
                last_cycle = now
                if self._DEBUG:
                    print("bot_loop tick elapsed_ms=%.0f" % elapsed_ms)
            else:
                time.sleep(0.005)


class Task():
    def __init__(self, object=None, func='', params=None):
        if params is None:
            params = []
        self._object = object
        self._func = func
        self._params = params

    def run(self):
        try:
            if self._object is not None:
                meth = getattr(self._object, self._func, None)
                if callable(meth):
                    if isinstance(self._params, (list, tuple)) and len(self._params) > 0:
                        meth(*self._params)
                    else:
                        meth()
            else:
                if callable(self._func):
                    self._func(self._params)
        except Exception as e:
            print("Task.run failed: func=%r params=%r error=%s" % (self._func, self._params, repr(e)))
            raise
