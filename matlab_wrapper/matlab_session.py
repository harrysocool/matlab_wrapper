# -*- coding: utf-8 -*-
"""
Copyright 2010-2013 Joakim Möller
Copyright 2014 Marek Rudnicki

This file is part of matlab_wrapper.

matlab_wrapper is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

matlab_wrapper is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with matlab_wrapper.  If not, see <http://www.gnu.org/licenses/>.
"""

from __future__ import print_function, division, absolute_import

import numpy as np
import platform
import sys
from os.path import join, dirname, isfile, realpath
import os

import ctypes
from ctypes import c_char_p, POINTER, c_size_t, c_bool, c_void_p, c_int

from matlab_wrapper.typeconv import np_to_mat

class mxArray(ctypes.Structure):
    pass


wrap_script = r"""
ERRORSTR = '';
try
    {0}
catch err
    ERRORSTR = sprintf('%s: %s\n', err.identifier, err.message);
    for i = 1:length(err.stack)
        ERRORSTR = sprintf('%sError: in fuction %s in file %s line %i\n', ERRORSTR, err.stack(i,1).name, err.stack(i,1).file, err.stack(i,1).line);
    end
end
if exist('ERRORSTR','var') == 0
    ERRORSTR='';
end
"""

class MatlabSession(object):
    """Matlab session.

    Parameters
    ----------
    options : str, optional
        Options that will be passed to MATLAB at the start,
        e.g. '-nosplash'.
    matlab_root : str or None, optional
        Root of the MATLAB installation.  If unsure, then start MATLAB
        and type `matlabroot`.  If `None`, then will be determined
        based on the `matlab` binary location.
    buffer_size : int, optional
        MATLAB output buffer size.  The output buffer can be accessed
        through `output_buffer` property.

    """
    def __init__(self, options='-nosplash', matlab_root=None, buffer_size=0):
        system = platform.system()


        ### Find MATLAB's root path
        if matlab_root is None:
            path_dirs = os.environ.get("PATH").split(os.pathsep)
            for path_dir in path_dirs:
                candidate = realpath(join(path_dir, 'matlab'))
                if isfile(candidate):
                    matlab_root = dirname(dirname(candidate))
                    break

        if matlab_root is None:
            raise RuntimeError("MATLAB location is unknown (set matlab_root)")


        ### Load libraries and start engine
        if system in ('Linux', 'Darwin'):
            self._libeng = ctypes.CDLL(
                join(matlab_root, 'bin', 'glnxa64', 'libeng.so')
            )
            self._libmx = ctypes.CDLL(
                join(matlab_root, 'bin', 'glnxa64', 'libmx.so')
            )
            executable = join(matlab_root, 'bin', 'matlab')
            command = "{} {}".format(executable, options)
            self._ep = self._libeng.engOpen( c_char_p(command) )

        # elif system=='Windows':
        #     self.engine = CDLL(join(matlab_root,'bin','glnxa64','libeng.dll'))
        #     self.mx = CDLL(join(matlab_root,'bin','glnxa64','libmx.dll'))
        #     self.ep = self.engine.engOpen(None)

        else:
            raise NotImplementedError("System {} not supported".format(system))


        if self._ep is None:
            raise RuntimeError(
                "Could not start matlab using command:\n\t{}".format(command)
            )


        ### Setup the output buffer
        if buffer_size != 0:
            self._output_buffer = ctypes.create_string_buffer(buffer_size)
            self._libeng.engOutputBuffer(
                self._ep,
                self._output_buffer,
                buffer_size-1
            )
        else:
            self._output_buffer = None



    def __del__(self):
        self._libeng.engClose(self._ep)


    @property
    def output_buffer(self):
        return self._output_buffer.value


    def eval(self, expression):
        """Evaluate `expression` in MATLAB engine.

        Parameters
        ----------
        expression : str
            Expression is passed to MATLAB engine and evaluated.

        """
        expression_wrapped = wrap_script.format(expression)


        ### Evaluate the expression
        self._libeng.engEvalString(
            self._ep,
            c_char_p(expression_wrapped)
        )

        ### Check for exceptions in MATLAB
        self._libeng.engGetVariable.restype = POINTER(mxArray)
        mxresult = self._libeng.engGetVariable(
            self._ep,
            c_char_p('ERRORSTR')
        )

        self._libmx.mxArrayToString.restype = c_char_p
        error_string = self._libmx.mxArrayToString(mxresult)

        if error_string != "":
            raise RuntimeError("Error from MATLAB\n{0}".format(error_string))



    def get(self, name):
        """Get variable `name` from MATLAB workspace.

        Parameters
        ----------
        name : str
            Name of the variable in MATLAB workspace.

        Returns
        -------
        array_like
            Value of the variable `name`.

        """
        self._libeng.engGetVariable.restype = POINTER(mxArray)
        pm = self._libeng.engGetVariable(self._ep, c_char_p(name))

        self._libmx.mxGetNumberOfDimensions.restype = c_size_t
        ndims = self._libmx.mxGetNumberOfDimensions(pm)

        self._libmx.mxGetDimensions.restype = POINTER(c_size_t)
        dims = self._libmx.mxGetDimensions(pm)

        self._libmx.mxGetNumberOfElements.restype = c_size_t
        numelems = self._libmx.mxGetNumberOfElements(pm)

        self._libmx.mxGetElementSize.restype = c_size_t
        elem_size = self._libmx.mxGetElementSize(pm)

        self._libmx.mxGetClassName.restype = c_char_p
        class_name = self._libmx.mxGetClassName(pm)

        self._libmx.mxIsNumeric.restype = c_bool
        is_numeric = self._libmx.mxIsNumeric(pm)

        self._libmx.mxIsComplex.restype = c_bool
        is_complex = self._libmx.mxIsComplex(pm)

        self._libmx.mxGetData.restype = POINTER(c_void_p)
        data = self._libmx.mxGetData(pm)

        self._libmx.mxGetImagData.restype = POINTER(c_void_p)
        imag_data = self._libmx.mxGetImagData(pm)

        if is_numeric:
            datasize = numelems*elem_size

            real_buffer = ctypes.create_string_buffer(datasize)
            ctypes.memmove(real_buffer, data, datasize)
            pyarray = np.ndarray(
                buffer=real_buffer,
                shape=dims[:ndims],
                dtype=class_name,
                order='F'
            )

            if is_complex:
                imag_buffer = ctypes.create_string_buffer(datasize)
                ctypes.memmove(imag_buffer, imag_data, datasize)
                pyarray_imag = np.ndarray(
                    buffer=imag_buffer,
                    shape=dims[:ndims],
                    dtype=class_name,
                    order='F'
                )

                pyarray = pyarray + pyarray_imag * 1j

            out = pyarray.squeeze()


        elif class_name == 'char':
            datasize = numelems + 1

            pystring = ctypes.create_string_buffer(datasize+1)
            self._libmx.mxGetString(pm, pystring, datasize)

            out = pystring.value


        elif class_name == 'logical':
            datasize = numelems*elem_size

            buf = ctypes.create_string_buffer(datasize)
            ctypes.memmove(buf, data, datasize)

            pyarray = np.ndarray(
                buffer=buf,
                shape=dims[:ndims],
                dtype='bool',
                order='F'
            )

            out = pyarray.squeeze()

        else:
            raise NotImplementedError('{}-arrays are not implemented'.format(class_name))


        self._libmx.mxDestroyArray.restype = POINTER(mxArray)
        self._libmx.mxDestroyArray(pm)

        return out




    def put(self, name, value):
        """Put a variable to MATLAB workspace.

        """
        if isinstance(value, str):
            self._libmx.mxCreateString.restype = POINTER(mxArray)
            pm = self._libmx.mxCreateString(c_char_p(value))

        elif isinstance(value, dict):
            raise NotImplementedError('dicts are not supported.')

        else:
            value = np.array(value, ndmin=2)


        if isinstance(value, np.ndarray) and value.dtype.kind in ['i','u','f','c','b']:
            dim = value.ctypes.shape_as(c_size_t)
            complex_flag = (value.dtype.kind == 'c')

            self._libmx.mxCreateNumericArray.restype = POINTER(mxArray)
            pm = self._libmx.mxCreateNumericArray(
                c_size_t(value.ndim),
                dim,
                np_to_mat(value.dtype),
                c_int(complex_flag)
            )

            self._libmx.mxGetData.restype = POINTER(c_void_p)
            mat_data = self._libmx.mxGetData(pm)
            np_data = value.real.tostring('F')
            ctypes.memmove(mat_data, np_data, len(np_data))

            if complex_flag:
                self._libmx.mxGetImagData.restype = POINTER(c_void_p)
                mat_data = self._libmx.mxGetImagData(pm)
                np_data = value.imag.tostring('F')
                ctypes.memmove(mat_data, np_data, len(np_data))


        # elif pyvariable.dtype.kind =='S':
        #     dim = pyvariable.ctypes.shape_as(c_size_t)
        #     self._libmx.mxCreateCharArray.restype=POINTER(mxArray)
        #     mx = self._libmx.mxCreateNumericArray(c_size_t(pyvariable.ndim),
        #                                           dim)
        #     self._libmx.mxGetData.restype=POINTER(c_void_p)
        #     data_old = self._libmx.mxGetData(mx)
        #     datastring = pyvariable.tostring('F')
        #     n_datastring = len(datastring)
        #     memmove(data_old,datastring,n_datastring)
        # elif pyvariable.dtype.kind =='O':
        #     raise NotImplementedError('Object arrays are not supported')

        elif isinstance(value, np.ndarray):
            raise NotImplementedError('Type {} not supported.'.format(value.dtype))


        self._libeng.engPutVariable(self._ep, c_char_p(name), pm)

        self._libmx.mxDestroyArray.restype = POINTER(mxArray)
        self._libmx.mxDestroyArray(pm)