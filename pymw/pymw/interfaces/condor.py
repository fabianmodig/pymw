#!/usr/bin/env python
"""Provide a Condor interface for master worker computing with PyMW.
"""

__author__ = "Eric Heien <e-heien@ics.es.osaka-u.ac.jp>"
__date__ = "22 February 2009"

import subprocess
import os
import time
import sys
import cPickle
import threading

CONDOR_TEMPLATE = """Universe = vanilla
InitialDir = <INITIAL_DIR/>
Requirements = (OpSys == "WINNT60" || OpSys == "WINNT51")
Executable = <PYTHON_LOC/>
Error = <PYMW_ERROR/>
Log = <PYMW_LOG/>
Input = <PYMW_INPUT_FILE/>
Output = <PYMW_OUTPUT_FILE/>
Arguments = <PYMW_EXEC_NAME/>
ShouldTransferFiles = YES
WhenToTransferOutput = ON_EXIT
TransferInputFiles = <PYMW_EXEC_FILE/>
Queue"""

class CondorInterface:
    """Provides a simple interface for desktop grids running Condor."""
    def __init__(self, python_loc="", condor_submit_loc=""):
        if sys.platform.startswith("win"):
            if python_loc != "": self._python_loc = python_loc
            else: self._python_loc = "C:\\Python25\\python.exe"
            if condor_submit_loc != "": self._condor_submit_loc = condor_submit_loc
            else: self._condor_submit_loc = "C:\\condor\\bin\\condor_submit.exe"
        else:
            if python_loc != "": self._python_loc = python_loc
            else: self._python_loc = "/usr/local/bin/python"
            if condor_submit_loc != "": self._condor_submit_loc = condor_submit_loc
            else: self._condor_submit_loc = "condor_submit"
        self._task_list = []
        self._task_list_lock = threading.Lock()
        self._result_checker_running = False
        self.pymw_interface_modules = "cPickle", "sys"
        
    def _get_finished_tasks(self):
        while True:
            self._task_list_lock.acquire()
            for task in self._task_list:
                # Check for the output file
                # TODO: also check for an error file
                log_file = open(task[2],"r")
                log_data = log_file.read()
                log_file.close()
                if log_data.count("Job terminated") > 0:
                    # Delete log, error and submission files
                    try: os.remove(task[1])
                    except: pass
                    try: os.remove(task[2])
                    except: pass
                    try: os.remove(task[3])
                    except: pass
                    task[0].task_finished(None)    # notify the task
                    self._task_list.remove(task)
            
#            err_file = open(err_file_name,"r")
#            if err_file:
#                err_output = err_file.read()
#                err_file.close()
#            else: err_output = ""
#            if err_output != "" :
#                task_error = Exception("Executable failed with error:\n"+err_output)
            self._task_list_lock.release()
            if len(self._task_list) == 0:
                self._result_checker_running = False
                return
            time.sleep(0.2)
        
    def reserve_worker(self):
        return None
    
    def execute_task(self, task, worker):
        # Create a template for this task
        condor_template = CONDOR_TEMPLATE
        condor_template = condor_template.replace("<PYTHON_LOC/>", self._python_loc)
        condor_template = condor_template.replace("<INITIAL_DIR/>", os.getcwd())
        condor_template = condor_template.replace("<PYMW_EXEC_FILE/>", task._executable)
        condor_template = condor_template.replace("<PYMW_INPUT_FILE/>", task._input_arg)
        condor_template = condor_template.replace("<PYMW_OUTPUT_FILE/>", task._output_arg)
        condor_template = condor_template.replace("<PYMW_EXEC_NAME/>", task._executable.split('/')[1])
        err_file_name = "tasks/"+task._task_name+".err"
        condor_template = condor_template.replace("<PYMW_ERROR/>", err_file_name)
        log_file_name = "tasks/"+task._task_name+".log"
        condor_template = condor_template.replace("<PYMW_LOG/>", log_file_name)
        
        # Remove old files so we don't have problems
        try: os.remove(err_file_name)
        except: pass
        try: os.remove(log_file_name)
        except: pass
        
        # Write the template to a file
        submit_file_name = "tasks/"+str(task._task_name)+"_condor"
        submit_file = open(submit_file_name,"w")
        submit_file.write(condor_template)
        submit_file.close()
        
        if sys.platform.startswith("win"): cf=0x08000000
        else: cf=0
        
        try:
            # Submit the template file through condor_submit
            submit_process = subprocess.Popen(args=[self._condor_submit_loc, submit_file_name],
                                    creationflags=cf, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            # Wait for the process to finish
            proc_stdout, proc_stderr = submit_process.communicate()
            
            # TODO: check stdout for problems
            if proc_stderr != "":
                task.task_finished(Exception("condor_submit failed with error:\n"+proc_stderr))
                return
            
            self._task_list_lock.acquire()
            self._task_list.append([task, err_file_name, log_file_name, submit_file_name])
            self._task_list_lock.release()
            
            if not self._result_checker_running:
                self._result_checker_running = True
                self._task_finish_thread = threading.Thread(target=self._get_finished_tasks)
                self._task_finish_thread.start()
            
        except OSError:
            # TODO: check the actual error code
            task.task_finished(Exception("Could not find task submission program "+self._condor_submit_loc))
    
    def _cleanup(self):
        self._scan_finished_tasks = False
    
    def pymw_master_read(self, loc):
        infile = open(loc, 'r')
        obj = cPickle.Unpickler(infile).load()
        infile.close()
        return obj
    
    def pymw_master_write(self, output, loc):
        outfile = open(loc, 'w')
        cPickle.Pickler(outfile).dump(output)
        outfile.close()
    
    def pymw_worker_read(loc):
        obj = cPickle.Unpickler(sys.stdin).load()
        return obj
    
    def pymw_worker_write(output, loc):
        print cPickle.dumps(output)

    def pymw_worker_func(func_name_to_call):
        try:
            # Redirect stdout and stderr
            old_stdout, old_stderr = sys.stdout, sys.stderr
            sys.stdout, sys.stderr = cStringIO.StringIO(), cStringIO.StringIO()
            # Get the input data
            input_data = pymw_worker_read(0)
            if not input_data: input_data = ()
            # Execute the worker function
            result = func_name_to_call(*input_data)
            # Get any stdout/stderr printed during the worker execution
            out_str, err_str = sys.stdout.getvalue(), sys.stderr.getvalue()
            sys.stdout.close()
            sys.stderr.close()
            # Revert stdout/stderr to originals
            sys.stdout, sys.stderr = old_stdout, old_stderr
            pymw_worker_write([result, out_str, err_str], 0)
        except Exception, e:
            sys.stdout, sys.stderr = old_stdout, old_stderr
            exit(e)
