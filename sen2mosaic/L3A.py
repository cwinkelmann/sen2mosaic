import argparse
import os
import shutil
import subprocess

try:
    import xml.etree.cElementTree as ET
except ImportError:
    import xml.etree.ElementTree as ET


def setGipp(gipp, output_dir):
    """
    Tweaks options in L2A_GIPP.xml file to set output directory correctly.
    Returns the location of a temporary .gipp file, for input to L2A_Process
    """
    
    print "WARNING: It's not currently possible to set GIPP file options via this script. For now, make changes to the .GIPP file by hand."
    
    # Test that GIPP and output directory exist
    assert gipp != None, "GIPP file must be specified if you're changing sen2three options."
    assert os.path.isfile(gipp), "GIPP XML options file doesn't exist at the location %s."%gipp
    assert os.path.isdir(output_dir), "Output directory %s doesn't exist."%output_dir
    
    # Adds a trailing / to output_dir if not already specified
    output_dir = os.path.join(output_dir, '')
   
    # Read GIPP file
    tree = ET.ElementTree(file = gipp)
    root = tree.getroot()

    # Change output directory    
    root.find('Common_Section/Target_Directory').text = output_dir
    
    # Generate a temporary output file
    temp_gipp = tempfile.mktemp(suffix='.xml')
    
    # Ovewrite old GIPP file with new options
    tree.write(temp_gipp)
    
    return temp_gipp


def validateTile(tile):
    '''
    Validates the name structure of a Sentinel-2 tile
    '''
    
    # Tests whether string is in format ##XXX
    name_test = re.match("[0-9]{2}[A-Z]{3}$",tile)
    
    return bool(name_test)
    

def processToL3A(tile, gipp = None, input_dir = os.getcwd(), output_dir = os.getcwd()):
    """
    Processes Sentinel-2 level 2A files to level 3A with sen2three.
    Input a tile in format ##XXX, a directory containing L2A files, and an output directory.
    If input and output directories not specified, the program will read all L2A files and output to the present working directory.
    """
    
    # Remove trailing / from input and output directories if present
    input_dir = input_dir.rstrip('/')
    output_dir = output_dir.rstrip('/')
    
    # Test that input location contains appropriate files in .SAFE format
    infiles = glob.glob('%s/*_MSIL2A_*.SAFE'%input_dir)
    assert len(infiles) > 0, "Input files must be in .SAFE format."

    # Validate tile input format for search   
    assert validateTile(tile), "The tile name input (%s) does not match the format ##XXX (e.g. 36KWA)."%tile
    
    # Test whether directory contains files from only one tile. Sen2three will process everything in a directory, so this is important
    for i in infiles:
        assert i.split('_')[-2] == 'T%s'%tile, "The tile name input (%s) does not match all L2A files in input directory. As  sen2Three will process everything in a directory, each tile needs to be placed in its own directory."
    
    # Set options in L3 GIPP xml. Returns the modified .GIPP file
    if gipp != None:
        temp_gipp = setGipp(gipp, output_dir)
    
     # Set up sen2three command
    command = ['L3_Process']
    if gipp != None:
        command += ['--GIP_L3', temp_gipp]
    command += ['--clean', input_dir]
    
    # Run sen2three (L3_Process)
    subprocess.call(command)
    
    # Determine output file path
    outpath = glob.glob('%s/*_MSIL03_*_T%s_*.SAFE'%(output_dir, tile))[0]
    
    # Tidy up huge .database.h5 files. These files are very large, and aren't subsequently required.
    h5_files = glob.glob('%s/GRANULE/*/IMG_DATA/R*m/.database.h5'%outpath)
    
    for h5_file in h5_files:
        shutil.rmtree(h5_file)


def main(tile, gipp = None, input_dir = os.getcwd(), output_dir = os.getcwd()):
    """
    Process level 2A Sentinel-2 data from sen2cor to cloud free mosaics with sen2three. This script initiates sen2three from within Python.
    """

    # Do the processing    
    processToL3A(tile, input_dir = input_dir, output_dir = output_dir, gipp = gipp)


if __name__ == '__main__':

    # Set up command line parser
    parser = argparse.ArgumentParser(description = 'Process level 2A Sentinel-2 data from sen2cor to cloud free mosaics with sen2three. This script initiates sen2three from within Python.')
    
    # Required arguments
    parser.add_argument('-t', '--tile', type = str, help = "Sentinel 2 tile name, in format ##XXX")

    # Optional arguments
    parser.add_argument('input_dir', metavar = 'input_dir', nargs = 1, type = str, default = os.getcwd(), help = 'Directory where the Level-2A input files are located. By default this will be the current working directory.')
    parser.add_argument('-g', '--gipp', type = str, default = None, help = 'Optionally specify the L3_Process settings file (default = L3_GIPP.xml). Required if specifying output directory.')
    parser.add_argument('-o', '--output_dir', type = str, default = None, help = "Optionally specify an output directory. If nothing specified, atmospherically corrected images will be written to the same directory as input files.")
    
    # Get arguments
    args = parser.parse_args()
        
    # Run the script
    main(tile, gipp = args.gipp, input_dir = input_dir, output_dir = args.output_dir)
