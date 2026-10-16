# Intro
Datasets with measurements of both solar electricity production and domestic electricity consumption separated into the major loads are interesting for research focussing on (i) local optimization of solar energy consumption and (ii) Non-Intrusive Load Monitoring. To this end, we publish the iHomeLab RAPT dataset consisting of electrical power traces from five houses in the greater Lucerne region in Switzerland spanning a period from 1.5 up to 3.5 years with a sampling frequency of five minutes. For each house the electrical energy consumption of the aggregated household and specific appliances such as dishwasher, washing machine, tumble dryer, hot water boiler, or heating pump were metered. Additionally, the data includes electric production data from PV panels for all five houses, and battery power flow measurement data from two houses. Thermal metadata is also provided for the three houses with a heating pump.

# Data Description
The data is release in two parts: 
    - a preprocessed version, 
        - measured sensor data is collected in files per house 
        - with a consistent sampling frequency of 5 minutes 
    - the raw data 
        - one file per sensor, all data from one house is contained within one folder 
        - with the original sampling frequency 

A detailed description of the dataset, corresponding metadata and the measurement setup can be found in 
**P. Huber, M. Ott, M. Friedli, A. Rumsch, A. Paice, "Residential Power Traces for Five Houses: the iHomeLab RAPT Dataset"**.

# Code 
The code to generate the preprocessed version of the dataset can be downloaded alongside the dataset. Check on [github](https://github.com/ihomelab/RAPT-dataset) if an updated versions is available.



