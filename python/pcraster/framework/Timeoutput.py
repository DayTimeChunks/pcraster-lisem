#!/usr/bin/env python
# -*- coding: utf-8 -*-

import pcraster
import os
import re
from decimal import Decimal

class TimeoutputTimeseries(object):
  """
  Class to create pcrcalc timeoutput style timeseries
  """
  def __init__(self, tssFilename, model, idMap=None, noHeader=False, save_path=None, period=None, sample_nr=None):
    """
	Method adapted to be able to save to a specific output folder (PAZ)
    save_path=None: folder path in coupled model.
    period=None: periods in between LISEM runs, corresponds to saving folders
    sample_nr=None: Montecarlo sample, coupled Dynamic framework only, use for saving
    """

    if not isinstance(tssFilename, str):
      raise Exception("timeseries output filename must be of type string")

    self._outputFilename = tssFilename
    self._maxId = 1
    self._spatialId = None
    self._spatialDatatype = None
    self._spatialIdGiven = False
    self._userModel = model
    self._writeHeader = not noHeader
    # array to store the timestep values
    self._sampleValues = None
    self._save_path = save_path  # PAZ
    self._period = period  # PAZ
    self.sample_nr = sample_nr

    _idMap = False
    if isinstance(idMap, str) or isinstance(idMap, pcraster._pcraster.Field):
      _idMap = True

    nrRows = self._userModel.nrTimeSteps() - self._userModel.firstTimeStep() + 1

    if _idMap:
      self._spatialId = idMap
      if isinstance(idMap, str):
        self._spatialId = pcraster.readmap(idMap)

      _allowdDataTypes = [pcraster.Nominal,pcraster.Ordinal,pcraster.Boolean]
      if self._spatialId.dataType() not in _allowdDataTypes:
        raise Exception("idMap must be of type Nominal, Ordinal or Boolean")

      if self._spatialId.isSpatial():
        self._maxId, valid = pcraster.cellvalue(pcraster.mapmaximum(pcraster.ordinal(self._spatialId)), 1)
      else:
        self._maxId = 1

      # cell indices of the sample locations
      self._sampleAddresses = []
      for cellId in range(1, self._maxId + 1):
        self._sampleAddresses.append(self._getIndex(cellId))

      self._spatialIdGiven = True
      nrCols = self._maxId
      self._sampleValues = [[Decimal("NaN")]  * nrCols for _ in [0] * nrRows]
    else:
      self._sampleValues = [[Decimal("NaN")]  * 1 for _ in [0] * nrRows]

  def _getIndex(self, cellId):
    """
    returns the cell index of a sample location
    """
    nrCells = pcraster.clone().nrRows() * pcraster.clone().nrCols()
    found = False
    cell = 1
    index = 0

    while found == False:
      if pcraster.cellvalue(self._spatialId, cell)[1] == True and pcraster.cellvalue(self._spatialId, cell)[0] == cellId:
        index = cell
        found = True
      cell += 1
      if cell > nrCells:
        raise RuntimeError("could not find a cell with the index number %d" % (cellId))

    return index


  def sample(self, expression):
    """
    Sampling the current values of 'expression' at the given locations for the current timestep
    """

    arrayRowPos = self._userModel.currentTimeStep() - self._userModel.firstTimeStep()

    #if isinstance(expression, float):
    #  expression = pcraster.scalar(expression)

    try:
      # store the data type for tss file header
      if self._spatialDatatype == None:
        self._spatialDatatype = str(expression.dataType())
    except AttributeError, e:
      datatype, sep, tail = str(e).partition(" ")
      msg = "Argument must be a PCRaster map, type %s given. If necessary use data conversion functions like scalar()" % (datatype)
      raise AttributeError(msg)

    if self._spatialIdGiven:
      if expression.dataType() == pcraster.Scalar or expression.dataType() == pcraster.Directional:
        tmp = pcraster.areaaverage(pcraster.spatial(expression), pcraster.spatial(self._spatialId))
      else:
        tmp = pcraster.areamajority(pcraster.spatial(expression), pcraster.spatial(self._spatialId))

      col = 0
      for cellIndex in self._sampleAddresses:
        value, valid = pcraster.cellvalue(tmp, cellIndex)
        if not valid:
          value = Decimal("NaN")

        self._sampleValues[arrayRowPos][col] = value
        col += 1
    else:
      if expression.dataType() == pcraster.Scalar or expression.dataType() == pcraster.Directional:
         tmp = pcraster.maptotal(pcraster.spatial(expression))\
               / pcraster.maptotal(pcraster.scalar(pcraster.defined(pcraster.spatial(expression))))
      else:
         tmp = pcraster.mapmaximum(pcraster.maptotal(pcraster.areamajority(pcraster.spatial(expression),\
               pcraster.spatial(pcraster.nominal(1)))))

      value, valid = pcraster.cellvalue(tmp, 1)
      if not valid:
        value = Decimal("NaN")

      self._sampleValues[arrayRowPos] = value

    if self._userModel.currentTimeStep() == self._userModel.nrTimeSteps():
       self._writeTssFile()


  def _writeFileHeader(self, outputFilename):
    """
    writes header part of tss file
    """
    outputFile = open(outputFilename, "w")
    # header
    outputFile.write("timeseries " + self._spatialDatatype.lower() + "\n")
    outputFile.write(str(self._maxId + 1) + "\n")
    outputFile.write("timestep\n")
    for colId in range(1, self._maxId + 1):
      outputFile.write(str(colId) + "\n")
    outputFile.close()


  def _writeTssFile(self):
    """
    writing timeseries to disk
    """
    #
    outputFilename =  self._configureOutputFilename(self._outputFilename)

    outputFile = None
    if self._writeHeader == True:
      self._writeFileHeader(outputFilename)
      outputFile = open(outputFilename, "a")
    else:
      outputFile = open(outputFilename, "w")

    assert outputFile

    start = self._userModel.firstTimeStep()
    end = self._userModel.nrTimeSteps() + 1

    for timestep in range(start, end):
      row = ""
      row += " %8g" % timestep
      if self._spatialIdGiven:
        for cellId in range(0, self._maxId):
          value = self._sampleValues[timestep - start][cellId]
          if isinstance(value, Decimal):
            row += "           1e31"
          else:
            row += " %14g" % (value)
        row += "\n"
      else:
        value = self._sampleValues[timestep - start]
        if isinstance(value, Decimal):
          row += "           1e31"
        else:
          row += " %14g" % (value)
        row += "\n"

      outputFile.write(row)

    outputFile.close()


  def _configureOutputFilename(self, filename):
    """
    generates filename
    appends timeseries file extension if necessary
    prepends sample directory if used in stochastic
    """

    # test if suffix or path is given
    head, tail = os.path.split(filename)

    if not re.search("\.tss", tail):
      # content,sep,comment = filename.partition("-")
      # filename = content + "Tss" + sep + comment + ".tss"
      filename = tail + ".tss"

    # for stochastic add sample directory
    if hasattr(self._userModel, "nrSamples"):
	  filename = os.path.join(str(self._userModel.currentSampleNumber()), filename)
      
    elif self._save_path is not None:  # PAZ
      if self.sample_nr is not None:
        new_path = self._save_path + "Bs" + str(self.sample_nr) + "\\" + str(self._period)
      else:
        new_path = self._save_path + str(self._period)
        
      filename = os.path.join(new_path, filename)
          

    return filename
