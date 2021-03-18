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
# Present a stepper motor, driven by the Adafruit Stepper Motor Bonnet on a
# Raspberry Pi, as an IoT device over MQTT, controllable and monitorable via MQTT
# messages when connected to a MQTT broker.
#
#
# ----------------------------------------------------------------------------------
 
import logging

import SmartBlindController
import MQTTSmartBlind

import time
import sys

####################################################################################
#
# run()
#
####################################################################################

def run():

	logging.basicConfig(
		format = '%(asctime)s %(levelname)s %(message)s',
		datefmt = '%Y/%m/%d %H:%M:%S',
		handlers = [
			# logging.FileHandler("Smart-Blind-IoT.log"),
			logging.StreamHandler()
		]
	 )

	controller = MQTTSmartBlind.MQTTSmartBlind(
		host = '192.168.1.159', 
		blindNo = 1,
		topicBase = 'smarthome',
		loggingLevel = logging.DEBUG
	)

	# controller2 = MQTTStepperMotorKit.MQTTStepperMotorKit(
	#    host = '192.168.1.159',
	#	 stepperNo = 2
	# )

	try:
		controller.run()	
	
	except:
		print("ERROR: ", sys.exc_info()[0], "occurred.")

####################################################################################
#
# main
#
####################################################################################

if __name__ == '__main__':
	run()

