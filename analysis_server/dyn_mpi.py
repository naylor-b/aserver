import sys
import traceback

from mpi4py import MPI

from analysis_server.proxy import ProblemProxy

def worker_loop(sw):
    """This will loop while receiving commands from the parent MPI process.

    Args
    ----

    sw : ProblemProxy
        Wrapper object for a particular Problem.
    """
    comm = MPI.Comm.Get_parent()

    while True:
        # get a command from the MPI parent process
        cmd, args = comm.bcast(None, root=0)
        if cmd == 'STOP':
            comm.Disconnect()
            break

        try:
            result = getattr(sw, cmd)(*args)
            tb = None
        except:
            result = None
            tb = traceback.format_exc()

        comm.gather((result, tb), root=0)


if __name__ == '__main__':
    args = sys.argv[1:]

    classname = args[0]
    instname = args[1]

    # the following assumes that filename=??? and directory=????, if they appear,
    # will appear in the specified order

    i = 2
    if len(args) > i and args[i].startswith('filename='):
        filename = args[i].split('=')[1].strip()
        i += 1
    else:
        filename = None

    if len(args) > i and args[i].startswith('directory='):
        directory = args[i].split('=')[1].strip()
        i += 1
    else:
        directory = ''

    # Note that we're just taking the remaining args from the command line as
    # strings, so if the object being constructed requires any non-string args,
    # this won't work.
    if len(args) > i:
        pass_args = args[i:]
    else:
        pass_args = ()


    sw = ProblemProxy()
    sw.init(classname, instaname, filename=filename, directory=directory, args=args)

    worker_loop(sw)
