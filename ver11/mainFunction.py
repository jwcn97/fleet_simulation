import pandas as pd
from chunks import chunks
from supportFunctions import *
from chargingFunctions import *
from drivingFunctions import *

def runSimulation(startTime, runTime, rcData, latLongData,
                fleetData, driveDataDF, allShiftsDF, breaksDF, pricesDF, algo):

    # INITIALISE MAIN DATAFRAMES WITH DATA AT START TIME
    #   Choose column names
    carCols = ["inDepot","battSize","battkW","battNeeded",
                "lat","long","destLat","destLong","destIndex",
                "chargePt","chargeRate","totalCost","totalDistance",
                "rcCount","rcChunks",
                "shiftIndex","latestStartShift","latestEndShift"]
    cpCols = ["maxRate","inUse"]
    simCols = ["time","car","chargeDiff","batt","event","costPerCharge","totalCost"]
    latLongCols = ["car","destinations"]

    #   Generate dataframes from csv inputs
    carDataDF, chargePtDF, latLongDF = generateDF(fleetData, latLongData, carCols, cpCols, latLongCols)

    sim = []
    depot = []
    driveDataByCar = {}
    for car in range(0, len(carDataDF)):
        # APPEND CARS INTO DEPOT AT START TIME
        if carDataDF.loc[car,'inDepot']: depot.append(car)
        # CREATE LIBRARY FOR DRIVING DATA
        findData = driveDataDF.loc[driveDataDF['car']==car]
        dataNoIndex = findData.reset_index(drop=True)
        driveDataByCar['%s' % car] = dataNoIndex
    
    # CREATE LIBRARY FOR SHIFTS BY CAR
    shiftsByCar = unpackShifts(carDataDF, allShiftsDF)
    # GENERATE STATUS OF DEPOT AT EVERY TIME
    depotStatus = generateDepotStatus(carDataDF, shiftsByCar)
    # RETRIEVE AVAILABLE POWER FROM FLEET DATA
    availablePower = getData(fleetData, 'availablePower')
    # CHOOSE START TIME
    time = startTime

    # RUN SIMULATION FOR ALL OF RUN TIME
    for i in range(0, runTime*chunks):
        # INITIALISE A VARIABLE TO CHECK FOR EVENT CHANGES
        eventChange = None
        # GET STATUS OF DEPOT
        depot = getDepotStatus(time, depotStatus)

        # *** RUN FUNCTIONS THAT INCLUDE WILL RECOGNISE CHANGES IN EVENTS ***
        eventChange, carDataDF, chargePtDF = inOutDepot(time, carDataDF, shiftsByCar, latLongDF, chargePtDF, eventChange)
        eventChange, carDataDF = readFullBattCars(carDataDF, sim, eventChange)
        eventChange, carDataDF = readCarsWithEnoughBatt(carDataDF, sim, eventChange)
        eventChange = readTariffChanges(time, pricesDF, eventChange)
        eventChange = predictExtraCharging(time, pricesDF, depot, carDataDF, shiftsByCar, availablePower, eventChange)

        # # PREDICT BATTERY NEEDED BY VEHICLE AND UPDATE CARDATADF
        carDataDF = predictBatteryNeeded(time, carDataDF, driveDataByCar, i, shiftsByCar, depotStatus, availablePower)

        # *** RUN FUNCTIONS AFFECTING CARS OUTSIDE THE DEPOT ***
        # DECREASE BATT/RAPID CHARGE CARS OUTSIDE THE DEPOT
        carDataDF, sim = driving(time, carDataDF, driveDataByCar, i, breaksDF, rcData, latLongDF, sim)

        # *** RUN FUNCTIONS AFFECTING CARS IN THE DEPOT ***
        # IF THERE IS AN EVENT CHANGE and THERE ARE CARS THAT REQUIRE CHARGING
        if (eventChange) and (len(depot) > 0):
            # RUN CHARGING ALGORITHM
            carDataDF = algo(time, carDataDF, depot, shiftsByCar, availablePower, chargePtDF, pricesDF, eventChange)

        # CHARGE/READ WAITING CARS IN THE DEPOT
        carDataDF, sim = charge(time, carDataDF, sim, pricesDF)

        # FORMAT TOTAL COST COLUMN IN SIMULATION DF
        sim = adjustTotalCost(time, sim)

        # INCREMENT TIME OF SIMULATION
        time = incrementTime(time)

    # CONVERT SIMULATION LIST TO DATAFRAME
    simulationDF = pd.DataFrame.from_records(sim, columns=simCols)

    print(carDataDF['totalCost'].sum())

    return simulationDF, carDataDF['rcCount'].sum(), carDataDF['totalCost'].sum()