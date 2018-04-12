#!/usr/bin/env python

import argparse
import datetime
import glob
import numpy as np
import os
import re
import shutil
import signal
import subprocess
import xml.etree.ElementTree as ET

import pdb


def _runCommand(command, verbose = False):
    """
    Function to capture KeyboardInterrupt.
    Idea from: https://stackoverflow.com/questions/38487972/target-keyboardinterrupt-to-subprocess

    Args:
        command: A list containing a command for subprocess.Popen().
    """
    
    try:
        p = None

        # Register handler to pass keyboard interrupt to the subprocess
        def handler(sig, frame):
            if p:
                p.send_signal(signal.SIGINT)
            else:
                raise KeyboardInterrupt
                
        signal.signal(signal.SIGINT, handler)
        
        #p = subprocess.Popen(command)
        p = subprocess.Popen(command, stdout = subprocess.PIPE, stderr = subprocess.PIPE)
        
        if verbose:
            for stdout_line in iter(p.stdout.readline, ""):
                print stdout_line
        
        text = p.communicate()[0]
                
        if p.wait():
            raise Exception('Command failed: %s'%' '.join(command))
        
    finally:
        # Reset handler
        signal.signal(signal.SIGINT, signal.SIG_DFL)
    
    return text.decode('utf-8').split('/n')


def _validateTile(tile):
    '''
    Validate the name structure of a Sentinel-2 tile. This tests whether the input tile format is correct.
    
    Args:
        tile: A string containing the name of the tile to to download.
    
    Returns:
        A boolean, True if correct, False if not.
    '''
    
    # Tests whether string is in format ##XXX
    name_test = re.match("[0-9]{2}[A-Z]{3}$",tile)
    
    return bool(name_test)


def _getDate(infile):
    '''
    Return a datetime object for an input GRANULE.
    
    Args:
        infile: A Sentinel-2 level 2A granule.
    Returns:
        A datetime object
    '''
    
    timestring = infile.split('/')[-1].split('_')[-1].split('T')[0]
    
    return datetime.datetime.strptime(timestring, '%Y%m%d')


def _getResolutions(infile):
    '''
    Return the resolutions available for an input GRANULE.
    
    Args:
        infile: A Sentinel-2 level 2A granule.
    Returns:
        A list of resolutions available
    '''
    
    res_dirs = glob.glob('%s/IMG_DATA/R*m'%infile)
    
    resolutions = [int(i.split('/')[-1].lstrip('R').rstrip('m')) for i in res_dirs]
    
    return resolutions
   

def _validateInput(tile, input_dir = os.getcwd(), start = '20150101', end = datetime.datetime.today().strftime('%Y%m%d'), resolution = 0):
    """_validateInput(tile, input_dir = os.getcwd(), start = '20150101', end = datetime.datetime.today().strftime('%Y%m%d'), resolution = 0)
    
    Test whether appropriate input files exist in the input directory
    
    Args:
        tile: A Sentinel-2 tile (stripped of preceding T).
        input_dir: Input directory
        start: start date in format YYYYMMDD. Defaults to beginning of Sentinel-2 era.
        end: end date in format YYYYMMDD. Defaults to today's date.
        resolution: The resolution to be processed (10, 20, 60, or 0 for all three)
    """
      
    # Test that input location contains level 2A files for tile.
    infiles = glob.glob('%s/S2?_MSIL2A_*.SAFE/GRANULE/*T%s*'%(input_dir,tile))
    
    assert len(infiles) >= 1, "Input directory must contain at least one Sentinel-2 level 2A file from tile T%s."%tile
    
    # Test that input location contains at least one file within date range
    dates = np.array([_getDate(i) for i in infiles])
    
    valid_dates = np.logical_and(dates >= datetime.datetime.strptime(start, '%Y%m%d'), dates <= datetime.datetime.strptime(end, '%Y%m%d'))

    assert valid_dates.sum() > 0, "Input directory must contain at least one file between dates %s and %s."%(start, end)
    
    # Test that all files within date range contain data at the appropriate resolution
    resolutions = np.array([_getResolutions(i) for i in infiles], dtype = np.object)[valid_dates]
    
    valid_res_list = [10, 20, 60] if resolution == 0 else [resolution]
    
    for file_res in resolutions:
        for valid_res in valid_res_list:
            assert valid_res in file_res, "All input files must have your specified resolution. If you've opted to process all resolutions, check that all input files have data for 10, 20 and 60 m."
    
    

def getL3AFile(tile, start = '20150101'):
    """
    
    Determine the level 3A tile path name from an input file (level 2A) tile.
    
    Args:
        tile: Sentinel-2 tile, in format '##XXX' or 'T##XXX'.
        start: Start date to process, in format 'YYYYMMDD' Defaults to start of Sentinel-2 era.
    Returns:
        A format string for the level 3A Sentinel-2 .SAFE file that will be generated by sen2three.
    """
        
    # Generate expected file pattern
    L3_format = 'S2?_MSIL03_????????T??????_N????_R???_T%s_%sT000000.SAFE'%(tile, start)
    
    return L3_format


def _setGipp(gipp, tile, output_dir = os.getcwd(), start = '20150101', end = datetime.datetime.today().strftime('%Y%m%d'), algorithm = 'TEMP_HOMOGENEITY'):
    """_setGipp(gipp, tile, output_dir = os.getcwd(), start = '20150101', end = datetime.datetime.today().strftime('%Y%m%d'), algorithm = 'TEMP_HOMOGENEITY')
    
    Function that tweaks options in sen2threes's L3_GIPP.xml file to specify various options.
    
    Args:
        gipp: The path to a copy of the L3_GIPP.xml file.
        tile: Sentinel-2 tile, in format '##XXX' or 'T##XXX'.
        input_dir: Directory containing level 2A Sentinel-2 .SAFE files. Defaults to current working directory.
        output_dir: Output directory. Defaults to current working directory.
        start: Start date to process, in format 'YYYYMMDD' Defaults to start of Sentinel-2 era.
        end: End date to process, in format 'YYYYMMDD' Defaults to today's date.
        algorithm: Compositing algorithm (one of 'MOST_RECENT', 'TEMP_HOMOGENEITY', 'RADIOMETRIC_QUALITY', 'AVERAGE'). Defaults to 'TEMP_HOMOGENEITY'.
        
    Returns:
        The directory location of a temporary .gipp file, for input to L2A_Process
    """
    
    # Test that GIPP and output directory exist
    assert gipp != None, "GIPP file must be specified if you're changing sen2three options."
    assert os.path.isfile(gipp), "GIPP XML options file doesn't exist at the location %s."%gipp  
    assert os.path.isdir(output_dir), "Output directory %s doesn't exist."%output_dir
    assert algorithm in ['MOST_RECENT', 'TEMP_HOMOGENEITY', 'RADIOMETRIC_QUALITY', 'AVERAGE'], "sen2three algorithm %s must be one of 'MOST_RECENT', 'TEMP_HOMOGENEITY', 'RADIOMETRIC_QUALITY', or 'AVERAGE'. You input %s."%str(algorithm)
    
    # Adds a trailing / to output_dir if not already specified
    output_dir = os.path.join(output_dir, '')
    
    # Read GIPP file
    tree = ET.ElementTree(file = gipp)
    root = tree.getroot()
    
    # Change output directory    
    root.find('Common_Section/Target_Directory').text = output_dir
    
    # Set Min_Time
    root.find('L3_Synthesis/Min_Time').text = '%s-%s-%sT00:00:00Z'%(start[:4], start[4:6], start[6:])
    
    # Set Max_Time
    root.find('L3_Synthesis/Max_Time').text = '%s-%s-%sT23:59:59Z'%(end[:4], end[4:6], end[6:])
    
    # Set tile filer
    root.find('L3_Synthesis/Tile_Filter').text = 'T%s'%tile
    
    # Set algorithm
    root.find('L3_Synthesis/Algorithm').text = algorithm
    
    # Get location of gipp file
    gipp_file = os.path.abspath(os.path.expanduser('~/sen2three/cfg/L3_GIPP.xml'))
    
    # Ovewrite old GIPP file with new options
    tree.write(gipp_file)
    
    return gipp_file


def processToL3A(tile, input_dir = os.getcwd(), output_dir = os.getcwd(), start = '20150101', end = datetime.datetime.today().strftime('%Y%m%d'), algorithm = 'TEMP_HOMOGENEITY', resolution = 0, verbose = False):
    """processToL3A(tile, input_dir = os.getcwd(), output_dir = os.getcwd(), start = '20150101', end = datetime.datetime.today().strftime('%Y%m%d'), resolution = 0, verbose = False):
    
    Processes Sentinel-2 level 2A files to level 3A with sen2three.
    
    Args:
        tile: Sentinel-2 tile, in format '##XXX' or 'T##XXX'.
        input_dir: Directory containing level 2A Sentinel-2 .SAFE files. Defaults to current working directory.
        output_dir: Output directory. Defaults to current working directory.
        start: Start date to process, in format 'YYYYMMDD' Defaults to start of Sentinel-2 era.
        end: End date to process, in format 'YYYYMMDD' Defaults to today's date.
        algorithm: Sen2three compositing algorithm (choose from 'MOST_RECENT', 'TEMP_HOMOGENEITY', 'RADIOMETRIC_QUALITY' or 'AVERAGE'). 'TEMP_HOMOGENEITY' is the default setting.
        resolution: Process only a single Sentinel-2 resolution (10, 20 or 60). Defaults to 0, meaning process all three.
        verbose: Print script progress.
    """
      
    # Cleanse input formats.
    input_dir = os.path.abspath(input_dir).rstrip('/')
    output_dir = os.path.abspath(output_dir).rstrip('/')
    tile = tile.lstrip('T')
    
    # Test that tile is properly formatted
    assert _validateTile(tile), "Tile %s is not a correctly formatted Sentinel-2 tile (e.g. T36KWA)."%str(tile)
    
    # Test that resolution is appropriate
    assert resolution in [0, 10, 20, 60], "Resolution must be set to 10, 20, 60, or 0 (all)"
    
    # Test that appropriate inputs exist
    _validateInput(tile, input_dir = input_dir, start = start, end = end, resolution = resolution)
        
    # Determine output filename
    outpath = getL3AFile(tile, start = start)
    
    # Check if output file already exists
    if len(glob.glob('%s/%s'%(output_dir,outpath))):
        raise ValueError('An output file with pattern %s already exists in output directory! Delete it to run L3_Process.'%outpath)
    
    # Get location of exemplar gipp file for modification
    gipp = '/'.join(os.path.abspath(__file__).split('/')[:-2] + ['cfg','L3_GIPP.xml'])
    
    # Set options in L3 GIPP xml. Returns the modified .GIPP file. This prevents concurrency issues with multiple instances.
    gipp_file = _setGipp(gipp, tile, output_dir = output_dir, start = start, end = end, algorithm = algorithm)
        
    # Set up sen2three command
    command = ['L3_Process', input_dir, '--clean']
    
    # If only processing one resolution
    if resolution != 0:
        command += ['--resolution', str(resolution)]
    
    # Print command for user info
    if verbose: print ' '.join(command)
       
    # Do the processing
    output_text = _runCommand(command, verbose = verbose)
    
    # Tidy up huge .database.h5 files. These files are very large, and aren't subsequently required. May no longer be an issue with sen2three v 1.1.0.
    h5_files = glob.glob('%s/%s/GRANULE/*T%s*/IMG_DATA/R*m/.database.h5'%(output_dir,outpath, tile))
    
    for h5_file in h5_files:
        os.remove(h5_file)


def testCompletion(tile, output_dir = os.getcwd(), start = '20150101', end = datetime.datetime.today().strftime('%Y%m%d'), resolution = 0):
    """
    Test for successful completion of sen2three processing.
    
    Args:
        tile: Sentinel-2 tile, in format '##XXX' or 'T##XXX'.
        output_dir: Output directory. Defaults to current working directory.
        start: Start date to process, in format 'YYYYMMDD' Defaults to start of Sentinel-2 era.
        end: End date to process, in format 'YYYYMMDD' Defaults to today's date.
        resolution: Test for only a single resolution (10, 20 or 60). Defaults to 0 (all three resolutions).
    Returns:

    """
    
    # Test that resolution is reasonable
    assert resolution in [0, 10, 20, 60], "Input resolution must be 10, 20, 60, or 0 (for all resolutions). The input resolution was %s"%str(resolution)
    
    #Test that tile is properly formatted
    assert _validateTile(tile), "Tile %s is not a correctly formatted Sentinel-2 tile (e.g. T36KWA)."%str(tile)
    
    # Format output directory
    output_dir = os.path.abspath(output_dir).rstrip('/')
    
    file_creation_failure = False
    band_creation_failure = False
    
    L3_file = getL3AFile(tile, start = start)
    
    # Test that output file exists
    if len(glob.glob(L3_file)) == 0:
        file_creation_failure = True   
    
    file_pattern = '%s/%s/GRANULE/*/IMG_DATA/R%sm/L03_T%s_????????T??????_%s_%sm.jp2'%(output_dir,L3_file,'%s','%s','%s','%s')
    
    # Test all expected 10 m files are present
    if resolution == 0 or resolution == 10:
        
        for band in ['B02', 'B03', 'B04', 'B08', 'TCI', 'SCL']:
            
            if not len(glob.glob(file_pattern%('10',tile,band,'10'))) == 1:
                band_creation_failure = True
    
    # Test all expected 20 m files are present
    if resolution == 0 or resolution == 20:
        
        for band in ['B02', 'B03', 'B04', 'B05', 'B06', 'B07', 'B8A', 'B11', 'B12', 'TCI', 'SCL']:
            
            if not len(glob.glob(file_pattern%('20',tile,band,'20'))) == 1:
                band_creation_failure = True

    # Test all expected 60 m files are present
    if resolution == 0 or resolution == 60:
        
        for band in ['B01', 'B02', 'B03', 'B04', 'B05', 'B06', 'B07', 'B8A', 'B09', 'B11', 'B12', 'TCI', 'SCL']:
            
            if not len(glob.glob(file_pattern%('60',tile,band,'60'))) == 1:
                band_creation_failure = True
    
    # At present we only report failure/success. More work requried to get the type of failure.
    return np.logical_or(file_creation_failure, band_creation_failure) == False

    

def main(tile, input_dir = os.getcwd(), output_dir = os.getcwd(), start = '20150101', end = datetime.datetime.today().strftime('%Y%m%d'), algorithm = 'TEMP_HOMOGENEITY', resolution = 0, verbose = False):
    """main(tile, input_dir = os.getcwd(), output_dir = os.getcwd(), start = '20150101', end = datetime.datetime.today().strftime('%Y%m%d'), algorithm = 'TEMP_HOMOGENEITY', resolution = 0, verbose = False)
    
    Process level 2A Sentinel-2 data from sen2cor to cloud free composite images with sen2three. This script calls sen2three from within Python.
    
    Args:
        tile: Sentinel-2 tile, in format '##XXX' or 'T##XXX'.
        input_dir: Directory containing level 2A Sentinel-2 .SAFE files. Defaults to current working directory.
        output_dir: Output directory. Defaults to current working directory.
        start: Start date to process, in format 'YYYYMMDD' Defaults to start of Sentinel-2 era.
        end: End date to process, in format 'YYYYMMDD' Defaults to today's date.
        algorithm: Sen2three compositing algorithm (choose from 'MOST_RECENT', 'TEMP_HOMOGENEITY', 'RADIOMETRIC_QUALITY' or 'AVERAGE'). 'TEMP_HOMOGENEITY' is the default setting.
        resolution: Process only a single Sentinel-2 resolution (10, 20 or 60). Defaults to 0, meaning process all three.
        verbose: Print script progress.  
    """
    
    # Do the processing    
    processToL3A(tile, input_dir = input_dir, output_dir = output_dir, start = start, end = end, algorithm = algorithm, resolution = resolution, verbose = verbose)
        
    # Test for completion
    if testCompletion(tile, output_dir = output_dir, start = start, end = end) == False:
        print 'WARNING: %s did not complete processing.'%tile
    else:
        print 'Processing completed successfully on %s.'%tile



if __name__ == '__main__':

    # Set up command line parser
    parser = argparse.ArgumentParser(description = 'Process level 2A Sentinel-2 data from sen2cor to cloud free composite images with sen2three.')
    
    parser._action_groups.pop()
    required = parser.add_argument_group('Required arguments')
    optional = parser.add_argument_group('Optional arguments')

    # Required arguments
    required.add_argument('-t', '--tile', metavar = 'TILE', type = str, help = 'Sentinel-2 to process, in format T##XXX or ##XXX (e.g. T36KWA or 36KWA).')
    
    # Optional arguments
    optional.add_argument('input_dir', metavar = 'PATH', nargs = '*', type = str, default = [os.getcwd()], help = 'Directory where the Level-2A input files are located (e.g. PATH/TO/L2A_DIRECTORY/). Also supports multiple directories through wildcards (*), which will be processed in series. Defaults to current working directory.')
    optional.add_argument('-s', '--start', type = str, default = '20150101', help = "Start date for tiles to include in format YYYYMMDD. Defaults to processing all dates.")
    optional.add_argument('-e', '--end', type = str, default = datetime.datetime.today().strftime('%Y%m%d'), help = "End date for tiles to include in format YYYYMMDD. Defaults to processing all dates.")
    optional.add_argument('-o', '--output_dir', type = str, metavar = 'DIR', default = os.getcwd(), help = "Specify a directory to output level 3A file. If not specified, the composite image will be written to the same directory as input files.")
    optional.add_argument('-a', '--algorithm', type = str, metavar = 'STR', default = 'TEMP_HOMOGENEITY', help = "Compositing algorithm for sen2three. Select from 'MOST_RECENT', 'TEMP_HOMOGENEITY', 'RADIOMETRIC_QUALITY' or 'AVERAGE'. We recommend 'TEMP_HOMOGENEITY', which is the default setting.")
    optional.add_argument('-res', '--resolution', type = int, metavar = '10/20/60', default = 0, help = "Process only one of the Sentinel-2 resolutions, with options of 10, 20, or 60 m. Defaults to processing all three.")
    optional.add_argument('-v', '--verbose', action = 'store_true', default = False, help = 'Print progress.')
    
    # Get arguments
    args = parser.parse_args()
    
    for input_dir in args.input_dir:
        
        # Run the script
        main(args.tile, input_dir = input_dir, output_dir = args.output_dir, start = args.start, end = args.end, algorithm = args.algorithm, resolution = args.resolution, verbose = args.verbose)
