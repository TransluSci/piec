import pandas as pd
import numpy as np
import os

### FILE HANDLING CONVINIENCE FUNCTIONS ###

def metadata_and_data_to_csv(metadata, data, path):
    """
    Convenience function that takes two arbitrary dataframes and writes them to a csv
    one below the other with a space in between through a single UTF-8 handle (Section 8.1).
    Used nominally for a 1XN metadata df and a data df.

    :param metadata: dataframe containing metadata, standard is a 1XN table (many columns with one value each)
    :param data: dataframe containing time data captured from measurment, appended to csv below metadata
    :param path: path to save csv in
    """
    with open(path, "w", encoding="utf-8", newline="") as f:
        metadata.to_csv(f, index=False, header=True, lineterminator="\n")
        f.write("\n")
        data.to_csv(f, index=False, header=True, lineterminator="\n")
        f.flush()
        try:
            os.fsync(f.fileno())
        except (AttributeError, OSError):
            pass

def standard_csv_to_metadata_and_data(path, metadata_header_row=0, data_header_row=2):
    """
    Convenience function that takes the piec standard 1xN metadata with data below and returns each as individual dataframes

    :param path: path to save csv in
    :param metadata_header_row: row where metadata starts (defaut row 0)
    :param data_header_row:  row where data starts (defaut row 2)
    """
    # Read metadata using its header row and assuming it has only one row of data
    metadata = pd.read_csv(path, header=metadata_header_row, nrows=1)

    # Read data starting from its header row and continuing to the end of the file
    data = pd.read_csv(path, header=data_header_row)

    return metadata, data

def create_measurement_filename(directory, measurement_type, notes="", type="csv"):
    """
    Creates a unique filename for a measurement file by checking for identical filenames
    and prepending an index to the filename if an identical one already exists in
    the target directory. Will also create the target directory if it does not already exist.
    
    Parameters:
    - directory (str): Target directory where measurement is to be saved.
    - measurement_type (str): Tag that is unique to the measurement type, e.g., "hyst" or "3pp".
    - notes (str): Extra string to add to the end of the filename, e.g., frequency and voltage info.
    - type (str): File extension, defaults to "csv".
    
    Returns:
    - filename (str): Full filepath of the given measurement in the form "{index}_{measurement_type}_{notes}.{type}"

    ***NOTE Made with help from ChatGPT LLM***
    """
    # Ensure the directory exists
    os.makedirs(directory, exist_ok=True)
    
    # Construct the base filename
    base_filename = f"{measurement_type}_{notes}.{type}"
    
    # Initialize index
    index = 0
    
    # Loop to find a unique filename
    while True:
        # Construct the full filepath
        filename = os.path.join(directory, f"{index}_{base_filename}")
        
        # Check if the file already exists
        if not os.path.exists(filename):
            break
        
        # Increment the index if the file exists
        index += 1
    
    return filename

### ARBITRARY WAVEFORM CONVINIENCE FUNCTIONS ###

def interpolate_sparse_to_dense(x_sparse, y_sparse, total_points=100):
    """
    Transform sparse arrays of x and y coordinates into a dense array of y coordinates
    linearly interpolated over N=total_points evenly-spaced x values.
    
    Parameters:
    - x_sparse (array-like): Sparse array of x coordinates.
    - y_sparse (array-like): Sparse array of y coordinates.
    - total_points (int): Number of interpolated points between each pair of coordinates.
    
    Returns:
    - y_dense (numpy array): Dense array of linearly interpolated y coordinates.

    ***NOTE Made with help from ChatGPT LLM***
    """
    y_dense = []

    # Iterate through each pair of adjacent sparse points
    for i in range(len(x_sparse) - 1):
        # Get the start and end points
        x_start, x_end = x_sparse[i], x_sparse[i + 1]
        y_start, y_end = y_sparse[i], y_sparse[i + 1]
        
        # Generate interpolated points between y_start and y_end
        n_to_interpolate = int(((x_sparse[i + 1]-x_sparse[i])/max(x_sparse))*total_points)
        y_interp = np.linspace(y_start, y_end, n_to_interpolate, endpoint=False)
        
        # Append the interpolated points
        y_dense.extend(y_interp)

    #add on duplicate points at the end to ensure array length == total_points (make up for int rounding error)
    while len(y_dense) < total_points:
        y_dense.append(y_dense[-1])

    return np.array(y_dense)

