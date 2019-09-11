import numpy as np
import math
import geopy
from geopy.distance import VincentyDistance
import time
from chunks import chunks
from supportFunctions import *


##################################################
# FUNCTIONS WHICH SUPPORT DRIVING
##################################################

# CHECK WHETHER IT IS A NON CHARGING BREAK
def breakTime(time, breaksDF):
    breakStart = getData(breaksDF, 'startBreak')
    breakEnd = getData(breaksDF, 'endBreak')

    if not breakStart == "None":
        if readTime(breakStart) <= time.time() < readTime(breakEnd):
            return True

# CHECK WHETHER VEHICLES REQUIRE RAPID CHARGE
#   UPDATE RAPID CHARGE CHUNKS IN CARDATADF and UPDATE RCCOUNT
def checkRC(carDataDF, drivingCarsDF, rcDuration, rcPerc):
    # FIND DURATION OF RAPID CHARGE IN CHUNKS
    rcChunks = int(np.ceil(rcDuration * chunks))

    # FOR CARS OUTSIDE OF DEPOT:
    #   * CHECK FOR CARS CURRENTLY RAPID CHARGING
    #   * THEN CHECK FOR CARS THAT NEED RAPID CHARGING
    for row in range(len(drivingCarsDF)):
        car = drivingCarsDF.index[row]

        # GET BATTERY AND BATTERY SIZE
        batt = carDataDF.loc[car, 'battkW']
        battSize = carDataDF.loc[car, 'battSize']
        # GET THE RAPID CHARGE STATUS OF VEHICLE
        chunkCount = carDataDF.loc[car, 'rcChunks']

        # IF CAR IS RAPID CHARGING AND REQUIRES MORE RAPID CHARGING:
        if 0 < chunkCount < rcChunks:
            # INCREMENT RAPID CHARGE CHUNKS COUNT
            carDataDF.loc[car, 'rcChunks'] += 1

        # IF CAR HAS NOT BEEN RAPID CHARGING, BUT NEEDS RAPID CHARGING (BATTERY < RC PERCENTAGE):
        elif batt < (battSize*(rcPerc/100)):
            # INCREMENT RAPID CHARGE CHUNKS COUNT
            carDataDF.loc[car, 'rcChunks'] += 1
            # INCREASE RAPID CHARGE COUNT
            carDataDF.loc[car, 'rcCount'] += 1

        # IF CAR HAS NOT BEEN RAPID CHARGING AND DOESN'T NEED RAPID CHARGING:
        else:
            # RESET RAPID CHARGE CHUNKS COUNT
            carDataDF.loc[car, 'rcChunks'] = 0
    
    return carDataDF

# DECREASE BATTERY WHILE DRIVING NORMALLY
def decreaseBatt(car, carDataDF, driveDataByCar, ind, nonChargingBreak, latLongDF):
    # READ PARAMETERS
    batt = carDataDF.loc[car, 'battkW']
    battSize = carDataDF.loc[car, 'battSize']
    drivingValues = driveDataByCar['0'].shape[0]

    # GET VALUE FOR MILEAGE AND MPKW
    if nonChargingBreak: mileage = 0
    else:                mileage = driveDataByCar[str(car % 4)].loc[ind % drivingValues, 'mileage']
    mpkw = driveDataByCar[str(car % 4)].loc[ind % drivingValues, 'mpkw']

    # CALCULATE RATE OF BATT DECREASE
    kwphr = mileage/mpkw

    # SET INPUTS FOR SIMULATION DF
    chargeDiff = round(-kwphr/chunks, 1)
    costPerCharge = 0

    # UPDATE BATTERY AND TOTAL DISTANCE OF CAR (IN MILES)
    carDataDF.loc[car,'battkW'] = batt - (kwphr/chunks)
    carDataDF.loc[car, 'totalDistance'] += (mileage/chunks)

    return carDataDF, kwphr, chargeDiff, costPerCharge

# RAPID CHARGE VEHICLE
def rapidCharge(car, carDataDF, rcRate, rcPrice, totalCost):
    # READ BATTERY and BATTERY SIZE
    batt = carDataDF.loc[car, 'battkW']
    battSize = carDataDF.loc[car, 'battSize']

    # CALCULATE BATTERY INCREASE
    if batt + rcRate/chunks > battSize: RCbattIncrease = battSize - batt
    else:                               RCbattIncrease = rcRate/chunks

    # UPDATE RAPID CHARGE COUNT AND TOTAL COST
    rcCost = rcPrice * RCbattIncrease
    totalCost += rcCost

    # UPDATE BATTERY AND TOTAL COST
    carDataDF.loc[car,'battkW'] = batt + RCbattIncrease
    carDataDF.loc[car,'totalCost'] += rcCost

    # SET INPUTS FOR SIMULATION DF
    chargeDiff = round(RCbattIncrease, 1)
    costPerCharge = round(rcCost, 2)

    return carDataDF, totalCost, chargeDiff, costPerCharge


#########################################################################
# LOOK AT CARS OUTSIDE THE DEPOT
#   FOR CARS THAT NEED RAPID CHARGING: RAPID CHARGE
#   FOR CARS THAT DON'T NEED RAPID CHARGING: DECREASE BATT
#########################################################################
def driving(time, carDataDF, driveDataByCar, breaksDF, rcData, latLongDF, simulationDF, ind):
    # EXTRACT RAPID CHARGE DATA
    rcPrice = getData(rcData, 'rcPrice')        # PRICE PER KW OF RAPID CHARGE (£ PER KW)
    rcDuration = getData(rcData, 'rcDuration')  # RAPID CHARGE DURATION (HRS)
    rcPerc = getData(rcData, 'rcPerc')          # WHAT PERCENTAGE TO START RAPID CHARGING (%)
    rcRate = getData(rcData, 'rcRate')          # RATE OF RAPID CHARGING (KW/HR)

    # FIND CARS OUTSIDE OF DEPOT
    drivingCarsDF = carDataDF.loc[carDataDF["inDepot"]==0]

    # UPDATE RAPID CHARGE CHUNKS IN CARDATADF and UPDATE RCCOUNT
    carDataDF = checkRC(carDataDF, drivingCarsDF, rcDuration, rcPerc)

    # GET OTHER PARAMETERS
    drivingValues = driveDataByCar['0'].shape[0]
    nonChargingBreak = breakTime(time, breaksDF)
    totalCost = carDataDF['totalCost'].sum()

    for rows in range(len(drivingCarsDF)):
        car = drivingCarsDF.index[rows]

        # READ BATTERY
        batt = carDataDF.loc[car, 'battkW']
        
        # ***** FOR CARS THAT DON'T NEED RAPID CHARGING, DECREASE BATT *****
        if carDataDF.loc[car, 'rcChunks'] == 0:
            # DECREASE BATTERY OF VEHICLE
            carDataDF, kwphr, chargeDiff, costPerCharge = decreaseBatt(car, carDataDF, driveDataByCar, ind, nonChargingBreak, latLongDF)
            # UPDATE RAPID CHARGE CHUNKS
            carDataDF.loc[car,'rcChunks'] = 0
            # UPDATE EVENT
            event = 'wait' if kwphr == 0.0 else 'drive'
        
        # ***** FOR CARS THAT NEED RAPID CHARGING, RAPID CHARGE *****
        else:
            # RAPID CHARGE VEHICLE
            carDataDF, totalCost, chargeDiff, costPerCharge = rapidCharge(car, carDataDF, rcRate, rcPrice, totalCost)
            # LABEL EVENT
            event = 'RC'

        # UPDATE SIMULATION ACCORDINGLY
        simulationDF = simulationDF.append({
            'time': time,
            'car': car,
            'chargeDiff': chargeDiff,
            'batt': round(batt, 1),
            'event': event,
            'costPerCharge': costPerCharge,
            'totalCost': round(totalCost, 2)
        }, ignore_index=True)

    return carDataDF, simulationDF

#########################################################################
# DOES NOT NECESSARILY RAPID CHARGE FOR THE SPECIFIED DURATION
# ONLY RAPID CHARGE UNTIL IT IS ENOUGH TO REACH DEPOT
#########################################################################
def rcSmartDriving(time, carDataDF, driveDataByCar, breaksDF, rcData, latLongDF, simulationDF, ind):
    # EXTRACT RAPID CHARGE DATA
    rcPrice = getData(rcData, 'rcPrice')        # PRICE PER KW OF RAPID CHARGE (£ PER KW)
    rcDuration = getData(rcData, 'rcDuration')  # RAPID CHARGE DURATION (HRS)
    rcPerc = getData(rcData, 'rcPerc')          # WHAT PERCENTAGE TO START RAPID CHARGING (%)
    rcRate = getData(rcData, 'rcRate')          # RATE OF RAPID CHARGING (KW/HR)

    # FIND CARS OUTSIDE OF DEPOT
    drivingCarsDF = carDataDF.loc[carDataDF["inDepot"]==0]

    # GET OTHER PARAMETERS
    drivingValues = driveDataByCar['0'].shape[0]
    nonChargingBreak = breakTime(time, breaksDF)
    totalCost = carDataDF['totalCost'].sum()

    for rows in range(len(drivingCarsDF)):
        car = drivingCarsDF.index[rows]

        # READ VEHICLE PARAMETERS
        batt = carDataDF.loc[car, 'battkW']
        battSize = carDataDF.loc[car, 'battSize']
        rcChunks = carDataDF.loc[car,'rcChunks']

        # FIND HRS VEHICLE STILL NEEDS TO DRIVE
        hrsLeft = (readTime(carDataDF.loc[car, 'latestEndShift']) - time).total_seconds()/3600
        buffer = battSize * 5/100
        kwphr = 4
        battNeeded = hrsLeft*kwphr + buffer

        # IF CAR HAS BEEN RAPID CHARGING AND STILL NEEDS RAPID CHARGING
        if (rcChunks > 0) and (batt < battNeeded < battSize):
            # RAPID CHARGE VEHICLE
            carDataDF, totalCost, chargeDiff, costPerCharge = rapidCharge(car, carDataDF, rcRate, rcPrice, totalCost)
            # UPDATE RC PARAMETERS
            carDataDF.loc[car,'rcChunks'] += 1
            # LABEL EVENT
            event = 'RC'

        # IF CAR HASN'T BEEN RAPID CHARGING BUT NEEDS RAPID CHARGING
        elif (batt < battSize*rcPerc/100) and (batt < battNeeded < battSize):
            # RAPID CHARGE VEHICLE
            carDataDF, totalCost, chargeDiff, costPerCharge = rapidCharge(car, carDataDF, rcRate, rcPrice, totalCost)
            # UPDATE RC PARAMETERS
            if rcChunks == 0: carDataDF.loc[car,'rcCount'] += 1
            carDataDF.loc[car,'rcChunks'] += 1
            # LABEL EVENT
            event = 'RC'

        # IF CAR DOESN'T NEED RAPID CHARGING, DECREASE BATT (DRIVE):
        else:
            # DECREASE BATTERY OF VEHICLE
            carDataDF, kwphr, chargeDiff, costPerCharge = decreaseBatt(car, carDataDF, driveDataByCar, ind, nonChargingBreak, latLongDF)
            # UPDATE RAPID CHARGE CHUNKS
            carDataDF.loc[car,'rcChunks'] = 0
            # UPDATE EVENT
            event = 'wait' if kwphr == 0.0 else 'drive'

        # UPDATE SIMULATION ACCORDINGLY
        simulationDF = simulationDF.append({
            'time': time,
            'car': car,
            'chargeDiff': chargeDiff,
            'batt': round(batt, 1),
            'event': event,
            'costPerCharge': costPerCharge,
            'totalCost': round(totalCost, 2)
        }, ignore_index=True)

    return carDataDF, simulationDF