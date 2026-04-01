"""
This is the top level instrument that dictates if something is 
scpi, dac, arduino, etc.

This class now includes the AutoCheckMeta framework for
automatic parameter validation and state tracking.
"""
import functools
import inspect
import time
import re
import json
import os
import numpy as np
import pandas as pd

# Placeholder PiecManager if utilities.py is not present
# and to make this file runnable for testing.
try:
    from .utilities import PiecManager
except ImportError:
    print("Warning: Could not import PiecManager. Using placeholder.")
    class PiecManager:
        def open_resource(self, address, **kwargs):
            # print(f"PiecManager: Opening {address} with {kwargs}")
            class DummyResource:
                def __init__(self, addr, **kwargs):
                    self.resource_name = addr
                def query(self, q): return f"DUMMY QUERY: {q}"
                def write(self, c): print(f"DUMMY WRITE: {c}")
                def read(self): return ""
                def query_binary_values(self, query, datatype='h', is_big_endian=True):
                    print(f"DUMMY BINARY QUERY: {query}")
                    return [0.0] * 10
                def query_ascii_values(self, query):
                    print(f"DUMMY ASCII QUERY: {query}")
                    return [0.0] * 10
            return DummyResource(address, **kwargs)

# --- Metaclass and Decorator for Auto-Checking ---

def auto_check_params(func):
    """
    Decorator to automatically call self._check_params on a method
    if the instance's `check_params` flag is True.
    Also converts all string arguments to lowercase.
    
    *** NEW: This decorator also updates the instrument's internal state
    (e.g., self._current_frequency) with any valid arguments passed.
    """
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        sig = inspect.signature(func)
        bound_args = sig.bind(self, *args, **kwargs)
        bound_args.apply_defaults()
        
        locals_dict = {k: v for k, v in bound_args.arguments.items() if k != 'self'}
        lower_params = convert_to_lowercase(locals_dict)
        
        # 1. Perform validation checks first
        if getattr(self, 'check_params', False):
            self._check_params(self, lower_params)
        
        # 3. Update bound_args with the lowercase values for the function call
        for key, value in lower_params.items():
            if key in bound_args.arguments:
                bound_args.arguments[key] = value
        
        # 4. Call the original function FIRST.
        #    If this function raises an error (like our manual validation),
        #    the decorator will stop here, and the state will NOT be updated.
        result = func(*bound_args.args, **bound_args.kwargs)

        # 2. --- STATE-TRACKING LOGIC ---
        #    This code only runs if the function call above SUCCEEDED.
        class_attr_keys = recursive_lower(get_class_attributes_from_instance(self)).keys()
        
        for key, value in lower_params.items():
            if key in class_attr_keys and value is not None:
                # This is the "writer"
                setattr(self, f"_current_{key}", value)

        return result
    
    return wrapper

class AutoCheckMeta(type):
    """
    Metaclass to apply the `auto_check_params` decorator to all
    public methods of a class (those not starting with '_').
    """
    def __new__(metacls, name, bases, class_dict):
        new_class_dict = {}
        for attr_name, attr_value in class_dict.items():
            if callable(attr_value) and not attr_name.startswith("_") and attr_name != '__init__':
                attr_value = auto_check_params(attr_value)
            new_class_dict[attr_name] = attr_value
        return super().__new__(metacls, name, bases, new_class_dict)

# --- Virtual Instrument (for testing) ---

class VirtualRMInstrument:
    """
    This class replaces the resource manager object in the virtual case,
    just needs to replace the .write() and .query() methods
    """
    def __init__(self, address, verbose:bool = False, **kwargs): # Added **kwargs and address
        self.verbose = verbose
        self.resource_name = address
        if self.verbose:
            print('INITIALIZING VIRTUAL RESOURCE MANAGER, VISA NOT CONNECTED')
        current_dir = os.path.dirname(__file__)

        json_path = os.path.join(current_dir, "virtual_scpi_queries.json")
        self.query_dict = {}
        try:
            with open(json_path, "r") as file:
                self.query_dict = json.load(file)
        except Exception as e:
            if self.verbose:
                print(f"Warning: Failed to load 'virtual_scpi_queries.json' at {json_path}: {e}")
            self.query_dict = {}
        
        # Ensure at least a default IDN exists if the file is empty or missing
        if "*IDN?" not in self.query_dict:
            self.query_dict["*IDN?"] = "Piec_Virtual_Instrument,Model_X,s/n_000,ver1.0"


    def query(self, input:str):
        time.sleep(0.01)
        if self.verbose: print('Query recieved: ',input)
        response = self.query_dict.get(input)
        if response is not None: return response
        else:
            print('QUERY: ', input, ' NOT IN virtual_scpi_queries.json')
            return "VIRTUAL QUERY:"+ input

    def write(self, input:str):
        time.sleep(0.01)
        if self.verbose: print('Write recieved: ',input)
    
    def write_binary_values(self, data, scaled_data, datatype='h'):
        time.sleep(0.01)
        if self.verbose: print('Binary write recieved: ', data, scaled_data, datatype)
            
    def query_binary_values(self, query, datatype='h', is_big_endian=True):
        time.sleep(0.01)
        if self.verbose: print('Binary query recieved: ', query)
        return [0] * 100 # Return a list of bytes

    def query_ascii_values(self, query):
        time.sleep(0.01)
        if self.verbose: print('ASCII query recieved: ', query)
        return [0.0] * 100 # Return a list of floats
        
    def read(self):
        if self.verbose: print('Read recieved')
        return ""

# --- Helper Functions for _check_params ---

def convert_to_lowercase(params):
    return {key: value.lower() if isinstance(value, str) else value for key, value in params.items()}

def is_contained(value, lst):
    """
    Robustly checks if a value is in a list, handling strings,
    integers, and floats.
    """
    if value is None: return True
    
    # 1. Direct Check
    if value in lst:
        return True
        
    # 2. String Check (for case-insensitivity)
    # e.g., "ac" in ["AC", "DC"]
    try:
        str_value = str(value).lower()
        str_list = [str(item).lower() for item in lst]
        if str_value in str_list:
            return True
    except:
        pass # Some items might not be convertible to string

    # 3. Numeric Check (for int/float equivalence)
    # e.g., 1.0 in [1, 2, 3]
    try:
        num_value = float(value)
        # This check works because in Python, 1.0 == 1 is True
        if num_value in lst:
            return True
        # Check floats in list (e.g. 1e-9 in [1e-9, 2e-9])
        if any(np.isclose(num_value, float(item)) for item in lst):
            return True
    except (ValueError, TypeError):
        pass # Value or list items not numeric

    return False

def is_value_between(value, num_tuple):
    if value is None: return True
    if type(value) is str: value = float(value)
    if len(num_tuple) != 2: raise ValueError("Tuple must contain exactly two numbers")
    lower_bound = num_tuple[0] if num_tuple[0] is not None else -float('inf')
    upper_bound = num_tuple[1] if num_tuple[1] is not None else float('inf')
    return lower_bound <= value <= upper_bound

def get_matching_keys(dict1, dict2):
    return list(set(dict1.keys()).intersection(dict2.keys()))

def get_class_attributes_from_instance(instance):
    cls = instance.__class__
    attributes = {}
    for base in reversed(cls.__mro__):
        attributes.update({attr: getattr(base, attr) 
                           for attr in base.__dict__ 
                           if not callable(getattr(base, attr)) and not attr.startswith("__")})
    return attributes

def recursive_lower(obj):
    if isinstance(obj, str): return obj.lower()
    if isinstance(obj, list): return [recursive_lower(item) for item in obj]
    if isinstance(obj, tuple): return tuple(recursive_lower(item) for item in obj)
    if isinstance(obj, dict):
        return { (k.lower() if isinstance(k, str) else k): recursive_lower(v)
                  for k, v in obj.items() }
    return obj

def exit_with_error(msg):
    raise ValueError(msg)

# --- Base Instrument Class ---

class Instrument(metaclass=AutoCheckMeta):
    """
    All an instrument is required to have is an address!
    This is the top-level class that provides connection management
    and the automatic parameter-checking framework.
    """

    def _initialize_state(self):
        """
        Initializes all _current_ attributes to None.
        """
        class_attributes = get_class_attributes_from_instance(self)
        for key in class_attributes.keys():
            setattr(self, f"_current_{key}", None)

    def __init__(self, address, check_params=False, verbose=False, **kwargs):
        """
        Opens the instrument and enables communication with it.
        
        Args:
            address (str): The VISA/serial address or "VIRTUAL".
            check_params (bool): Toggle for enabling/disabling auto-check.
            verbose (bool): If True, prints detailed debug info.
            **kwargs: Additional arguments for the resource manager 
                      (e.g., baud_rate=9600).
        """
        self.check_params = check_params
        self.verbose = verbose
        
        # Initialize all _current_ attributes to None
        class_attributes = get_class_attributes_from_instance(self)
        for key in class_attributes.keys():
            setattr(self, f"_current_{key}", None)
        
        self.virtual = (address.upper() == 'VIRTUAL')
        
        connection_kwargs = kwargs.copy()
        
        try:
            if self.virtual:
                self.instrument = VirtualRMInstrument(address, verbose=self.verbose, **connection_kwargs)
            else:
                pm = PiecManager()
                self.instrument = pm.open_resource(address, **connection_kwargs)
        
        except Exception as e:
            print(f"Error initializing instrument at {address}: {e}")
            print("Falling back to VIRTUAL mode.")
            self.instrument = VirtualRMInstrument(address, verbose=True, **connection_kwargs)
            self.virtual = True

    def idn(self):
        """
        At minimum ANY instrument in PIEC should be able to be id'd.
        This method should be overridden by child classes.
        """
        return "Default IDN function not implemented, please override in subclass"

    def _check_params(self, instance_self, locals_dict):
        """
        This is the parameter checking function that is called by the decorator.
        It validates function arguments against the class attributes.
        NOTE: If a class attribute is set to None, skips validation
        
        Args:
            instance_self (Instrument): The instance of the driver class.
            locals_dict (dict): The dictionary of arguments passed to the method.
        """
        class_attributes = get_class_attributes_from_instance(instance_self) # Use original case
        keys_to_check = get_matching_keys(locals_dict, class_attributes)
        
        for key in keys_to_check:

            class_attr_value = class_attributes.get(key)
            if class_attr_value is None:
                # This is the "off switch". If the class attribute is None,
                # it means validation is handled manually. Skip all checks.
                continue

            # Get the class attribute (e.g., self.sensitivity)
            attribute_value = getattr(instance_self, key)
            
            if attribute_value is None:
                # This is the "off switch". If a driver wants to handle
                # validation itself (like SRS830.set_sensitivity), it
                # should set its class attribute to `None`.
                continue
            
            # Get the value passed to the function (e.g., 1e-9)
            input_value = locals_dict[key]
            if input_value is None: continue # Skip None values

            # --- Simple Checks (List or Tuple) ---
            if isinstance(attribute_value, tuple):
                if not is_value_between(input_value, attribute_value):
                    exit_with_error(f"Error input value of \033[1m{input_value}\033[0m for arg \033[1m{key}\033[0m is out of acceptable Range \033[1m{attribute_value}\033[0m")
            
            elif isinstance(attribute_value, list):
                if not is_contained(input_value, attribute_value):
                    exit_with_error(f"Error input value of \033[1m{input_value}\033[0m for arg \033[1m{key}\033[0m is not in list of acceptable \033[1m{attribute_value}\033[0m")
            
            # --- Dictionary (Dependent) Check ---
            elif isinstance(attribute_value, dict):
                attribute_value_lower = recursive_lower(attribute_value)
                
                if not attribute_value_lower: continue # Skip empty dicts
                
                # Assume the first key in the dict is the dependency
                dependency_key = list(attribute_value_lower.keys())[0] # e.g., 'input_configuration'
                
                dep_value = None
                
                # 1. Check function arguments (stateless)
                #    e.g., set_something(sensitivity=1e-9, input_configuration='A')
                if dependency_key in locals_dict:
                    dep_value = locals_dict[dependency_key]
                
                # 2. Check for the *Standardized* state attribute (stateful)
                #    e.g. self._current_input_configuration
                standard_attr_name = f"_current_{dependency_key}"
                if hasattr(instance_self, standard_attr_name):
                    dep_value = getattr(instance_self, standard_attr_name)
                
                if dep_value is None:
                    # No value found in args OR in the standard state variable.
                    print(f"WARNING: Could not find dependency '{dependency_key}' in function args "
                          f"or in state variable 'self.{standard_attr_name}'. Skipping check for '{key}'.")
                    continue

                # Lowercase the found value (e.g., "A-B" -> "a-b")
                dep_value = str(dep_value).lower() 

                try:
                    # Use the dependency value to get the valid list/tuple
                    # e.g., attribute_value_lower['input_configuration']['a-b']
                    valid_range_or_list = attribute_value_lower[dependency_key][dep_value] 
                    
                    if isinstance(valid_range_or_list, tuple):
                         if not is_value_between(input_value, valid_range_or_list):
                            exit_with_error(f"Error: input value \033[1m{input_value}\033[0m for arg \033[1m{key}\033[0m is out of range \033[1m{valid_range_or_list}\033[0m (for {dependency_key} = '{dep_value}')")
                    elif isinstance(valid_range_or_list, list):
                        if not is_contained(input_value, valid_range_or_list): # Use robust check
                            exit_with_error(f"Error: input value \033[1m{input_value}\033[0m for arg \033[1m{key}\033[0m is not in list \033[1m{valid_range_or_list}\033[0m (for {dependency_key} = '{dep_value}')")
                
                except KeyError:
                    valid_options = list(attribute_value_lower[dependency_key].keys())
                    exit_with_error(f"Error: Invalid dependency value '\033[1m{dep_value}\033[0m' for '{dependency_key}'. Valid options are: {valid_options}")
                except Exception as e:
                    print(f"An error occurred during dependent parameter check for '{key}': {e}")