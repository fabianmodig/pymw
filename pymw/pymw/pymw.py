#!/usr/bin/env python
"""Provide a top level interface for master worker computing.
"""

__author__ = "Eric Heien <e-heien@ist.osaka-u.ac.jp>"
__date__ = "10 April 2008"

import threading
import cPickle
import time
import os
import types
import atexit
import interfaces.multicore_interface
import logging
import shelve
import decimal

# THINK ABOUT THIS
# New way of handling finished tasks:
# When a task is finished, it is put on the finished_task list
# This allows set task checks with wait_contain

class _SyncListIter:
    def __init__(self, list_obj):
        self._list_obj = list_obj
        self._pos = 0
    
    def __iter__(self):
        return self
    
    def next(self):
        if self._pos >= len(self._list_obj):
            raise StopIteration
        next_obj = self._list_obj._list[self._pos]
        self._pos = self._pos + 1
        return next_obj
    
class _SyncList:
    """Encapsulates a list with atomic operations and semaphore abilities."""
    def __init__(self):
        self._lock = threading.Lock()
        self._sem = threading.Semaphore(0)
        self._list = []
    
    def __len__(self):
        """Returns the length of the list."""
        self._lock.acquire()
        l_len = len(self._list)
        self._lock.release()
        return l_len
    
    def __iter__(self):
        return _SyncListIter(self)
    
    def append(self, item):
        """Atomically appends an item to the list and increments the semaphore."""
        self._lock.acquire()
        self._list.append(item)
        self._sem.release()
        self._lock.release()
    
    def wait_pop(self):
        """Waits for an item to appear in the list, and pops it off."""
        self._sem.acquire(blocking=True)
        self._lock.acquire()
        try:
            item = self._list.pop()
            return item
        except:
            return None
        finally:
            self._lock.release()

    def contains(self, item):
        """Checks if the list contains the specified item."""
        self._lock.acquire()
        n = self._list.count(item)
        self._lock.release()
        if n != 0: return True
        else: return False

class TaskException(Exception):
    """Represents an exception caused by a task failure."""
    def __init__(self, value):
        self.param = value
    def __str__(self):
        return repr(self.param)

class InterfaceException(Exception):
    """Represents an exception caused by an interface failure."""
    def __init__(self, value, detail_str=None):
        self.param = value
        if detail_str:
            self.details = detail_str
        else:
            self.details = ""
    def __str__(self):
        return repr(self.param)+"\n"+repr(self.details)

class PyMW_Task:
    """Represents a task to be executed."""
    def __init__(self, task_name, executable, input_data=None, input_arg=None, output_arg=None, file_loc="tasks"):
        self._finish_event = threading.Event()
        
        # Make sure executable is valid
        if not isinstance(executable, types.StringType) and not isinstance(executable, types.FunctionType):
            raise TypeError("executable must be a filename or Python function")
        
        self._executable = executable
        self._input_data = input_data
        self._output_data = None
        self._task_name = task_name

        # Set the input and output file locations
        if input_arg:
            self._input_arg = input_arg
        else:
            self._input_arg = file_loc + "/in_" + self._task_name + ".dat"
        
        if output_arg:
            self._output_arg = output_arg
        else:
            self._output_arg = file_loc + "/out_" + self._task_name + ".dat"

        # Pickle the input data
        logging.info("Pickling task "+str(self)+" into file "+self._input_arg)
        input_data_file = open(self._input_arg, 'w')
        cPickle.Pickler(input_data_file).dump(input_data)
        input_data_file.close()

        # Task time bookkeeping
        self._times = {"submit_time": time.time(), "execute_time": 0, "finish_time": 0}

    def __str__(self):
        return self._task_name
    
    def _state_data(self):
        return {"task_name": self._task_name, "executable": self._executable,
                "input_arg": self._input_arg, "output_arg": self._output_arg,
                "times": self._times, "finished": self._finish_event.isSet()}
    
    def task_finished(self, task_err=None):
        """This must be called by the interface class when the
        task finishes execution.  The result of execution should
        be in the file indicated by output_arg."""

        self._error = task_err
        
        try:
            output_data_file = open(self._output_arg, 'r')
            self._output_data = cPickle.Unpickler(output_data_file).load()
            output_data_file.close()
        except OSError:
            pass
        except IOError:
            pass

        logging.info("Task "+str(self)+" finished")
        self._times["finish_time"] = time.time()
        self._finish_event.set()

    def is_task_finished(self, wait):
        """Checks if the task is finished, and optionally waits for it to finish."""
        if not self._finish_event.isSet():
            if not wait:
                return False
            self._finish_event.wait()
        return True

    def get_total_time(self):
        """Get the time from task submission to completion.
        Returns None if task has not finished execution."""
        if self._times["finish_time"] != 0:
            return self._times["finish_time"] - self._times["submit_time"]
        else:
            return None

    def get_execution_time(self):
        """Get the time from start of task execution to completion.
        This may be different from the CPU time.
        Returns None if task has not finished execution."""
        if self._times["finish_time"] != 0:
            return self._times["finish_time"] - self._times["execute_time"]
        else:
            return None

    def cleanup(self):
        try:
            os.remove(self._input_arg)
            os.remove(self._output_arg)
        except OSError:
            pass
        
class PyMW_Scheduler:
    """Takes tasks submitted by user and sends them to the master-worker interface.
    This is done in a separate thread to allow for asynchronous program execution."""
    def __init__(self, task_list, interface):
        logging.info("PyMW_Scheduler started")
        self._task_list = task_list
        self._interface = interface
        self._finished = False
        _scheduler_thread = threading.Thread(target=self._scheduler)
        _scheduler_thread.start()
    
    def _scheduler(self):
        """Waits for submissions to the task list, then submits them to the interface."""
        while not self._finished:
            next_task = self._task_list.wait_pop()
            if next_task is not None:
                worker = self._interface.reserve_worker()
                next_task._times["execute_time"] = time.time()
                logging.info("Executing task"+str(next_task))
                task_thread = threading.Thread(target=self._interface.execute_task, args=(next_task, worker))
                task_thread.start()
        logging.info("PyMW_Scheduler finished")

    def _exit(self):
        """Signals the scheduler thread to exit."""
        self._finished = True
        self._task_list.append(None)

class PyMW_Master:
    """Provides functions for users to submit tasks to the underlying interface."""
    def __init__(self, interface=None, use_state_records=False, loglevel=logging.CRITICAL):
        logging.basicConfig(level=loglevel, format="%(asctime)s %(levelname)s %(message)s")

        if interface:
            self._interface = interface
        else:
            self._interface = interfaces.multicore_interface.MulticoreInterface()
        
        self._submitted_tasks = _SyncList()
        self._queued_tasks = _SyncList()
        self._use_state_records = use_state_records
        if self._use_state_records:
            self._state_shelve = shelve.open("pymw_state.dat")
        else:
            self._state_shelve = None
        
        self._task_dir_name = "tasks"
        self._cur_task_num = 0

        # Make the directory for input/output files, if it doesn't already exist
        try:
            os.mkdir(self._task_dir_name)
        except OSError, e: 
            #if e.errno <> errno.EEXIST: 
            #    raise
            pass

        self._scheduler = PyMW_Scheduler(self._queued_tasks, self._interface)
        atexit.register(self._cleanup)
    
    def submit_task(self, executable, input_data=None, new_task_name=None):
        """Creates and submits a task to the internal list for execution.
        Returns the created task for later use.
        executable can be either a filename (Python script) or a function."""
        
        # If using restored state, check whether this task has been submitted before
        if not new_task_name:
            task_name = str(executable)+"_"+str(self._cur_task_num)
            self._cur_task_num += 1
        else:
            task_name = new_task_name
        
        if self._use_state_records:
            for task in self._submitted_tasks:
                if str(task) == task_name:
                    return task
        
        new_task = PyMW_Task(task_name, executable, input_data=input_data, file_loc=self._task_dir_name)
        self._submitted_tasks.append(new_task)
        self._queued_tasks.append(new_task)
        return new_task
    
    def get_result(self, task=None, wait=True):
        """Gets the result of the executed task.
        If task is None, return the result of the next finished task.
        If wait is false and the task is not finished, returns None."""
        if task and not self._submitted_tasks.contains(task):
            raise TaskException("Task has not been submitted")
        
        if len(self._submitted_tasks) is 0:
            raise TaskException("No tasks yet submitted")
        
        if not task.is_task_finished(wait):
            return None, None

        if task._error:
            self._scheduler._exit()
            raise task._error
        
        return task, task._output_data
    
    def get_status(self):
        status = self._interface.get_status()
        status["tasks"] = self._submitted_tasks
        return status

    def _cleanup(self):
        try:
            self._interface._cleanup()
        except AttributeError:
            pass
        
        for task in self._submitted_tasks:
            task.cleanup()
        
        self._scheduler._exit()
        
        try:
            os.rmdir(self._task_dir_name)
        except OSError:
            pass

