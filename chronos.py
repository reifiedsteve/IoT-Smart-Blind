# python3.6

# ----------------------------------------------------------------------------------
#
#                             `_`     `_,_`  _'                                  `,`  
#                            -#@@- >O#@@@@u B@@>                                 8@E  
#    :)ilc}` `=|}uccccVu}r"   VQz `@@#Mhzk= |8M   `=v}ucccccuY),    `~v}uVVcccccV#@$  
#  ^Q@#EMqK.I#@QRdMqqMdRQ@@Q, Q@B `@@BqqqW^ W@@` e@@QRdMMMMbEQ@@8: i#@BOMqqqqqqqM#@$  
#  D@@`    )@@x          <@@T Q@B `@@q      W@@`>@@l          :@@z`#@d           Q@$  
#  D@#     ?@@@##########@@@} Q@B `@@q      W@@`^@@@##########@@@y`#@W           Q@$  
#  0@#     )@@d!::::::::::::` Q@B `@@M      W@@`<@@E!::::::::::::``#@b          `B@$  
#  D@#     `m@@#bGPP}         Q@B `@@q      W@@` 3@@BbPPPV         y@@QZPPPPPGME#@8=  
#  *yx       .*icywwv         )yv  }y>      ~yT   .^icywyL          .*]uywwwwycL^-   
#                                                                                    
#      (c) 2021 Reified Ltd.   W: www.reified.co.uk    E: sales@reified.co.uk
#
# ----------------------------------------------------------------------------------
#
# Classes for chronology-related concepts. A Stopwatch and a CountdownTimer.
#
# ----------------------------------------------------------------------------------
 
import time
 
####################################################################################
#
# class Stopwatch
#
####################################################################################

class Stopwatch:
 
    def __init__(self):
        self._start = time.time()
        self._stop = self._start
        self._accumulative = 0.0
        self._running = False;
        
    def start(self):
        self._start = time.time()
        self._running = True
		
    def stop(self):
        self._stop = time.time()
        elapsed = self._stop - self._start
        self._accumulative += elapsed
        self._start = self._stop
        self._running = False;
		
    def elapsed(self):
        end = time.time() if self._running else self._stop
        elapsed = end - self._start
        return elapsed + self._accumulative
		
    def restart(self):
        self._start = time.time()
        self._stop = self._start
        self._accumulative = 0.0
        self._running = True;

    def reset(self):
        self._start = time.time()
        self._stop = self._start
        self._accumulative = 0.0
        self._running = False;

    def _now():
        return time.time()

####################################################################################
#
# class CountdownTimer
#
####################################################################################

class CountdownTimer:
 
    def __init__(self, interval):
        self._stopwatch = Stopwatch()
        self._period = interval
		
    def start(self):
        self._stopwatch.start()
				
    def stop(self):
        self._stopwatch.stop()

    def remaining(self):
        timeSpent = self._stopwatch.elapsed()
        timeLeft = self._period - timeSpent
        return timeLeft if (timeLeft > 0.0) else 0.0
		
    def hasExpired(self):
        return self._stopwatch.elapsed() >= self._period
		
    def period(self, interval):
        self._period = interval

    def restart(self):
        self._stopwatch.restart()
	   
	   