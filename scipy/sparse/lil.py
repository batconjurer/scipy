"""LInked List sparse matrix class
"""

from __future__ import division, print_function, absolute_import

__docformat__ = "restructuredtext en"

__all__ = ['lil_matrix','isspmatrix_lil']

from bisect import bisect_left

import numpy as np
from scipy.lib.six.moves import xrange

from .base import spmatrix, isspmatrix
from .sputils import getdtype, isshape, issequence, isscalarlike, ismatrix

from warnings import warn
from .base import SparseEfficiencyWarning


class lil_matrix(spmatrix):
    """Row-based linked list sparse matrix

    This is an efficient structure for constructing sparse
    matrices incrementally.

    This can be instantiated in several ways:
        lil_matrix(D)
            with a dense matrix or rank-2 ndarray D

        lil_matrix(S)
            with another sparse matrix S (equivalent to S.tolil())

        lil_matrix((M, N), [dtype])
            to construct an empty matrix with shape (M, N)
            dtype is optional, defaulting to dtype='d'.

    Attributes
    ----------
    dtype : dtype
        Data type of the matrix
    shape : 2-tuple
        Shape of the matrix
    ndim : int
        Number of dimensions (this is always 2)
    nnz
        Number of nonzero elements
    data
        LIL format data array of the matrix
    rows
        LIL format row index array of the matrix

    Notes
    -----

    Sparse matrices can be used in arithmetic operations: they support
    addition, subtraction, multiplication, division, and matrix power.

    Advantages of the LIL format
        - supports flexible slicing
        - changes to the matrix sparsity structure are efficient

    Disadvantages of the LIL format
        - arithmetic operations LIL + LIL are slow (consider CSR or CSC)
        - slow column slicing (consider CSC)
        - slow matrix vector products (consider CSR or CSC)

    Intended Usage
        - LIL is a convenient format for constructing sparse matrices
        - once a matrix has been constructed, convert to CSR or
          CSC format for fast arithmetic and matrix vector operations
        - consider using the COO format when constructing large matrices

    Data Structure
        - An array (``self.rows``) of rows, each of which is a sorted
          list of column indices of non-zero elements.
        - The corresponding nonzero values are stored in similar
          fashion in ``self.data``.


    """

    def __init__(self, arg1, shape=None, dtype=None, copy=False):
        spmatrix.__init__(self)
        self.dtype = getdtype(dtype, arg1, default=float)

        # First get the shape
        if isspmatrix(arg1):
            if isspmatrix_lil(arg1) and copy:
                A = arg1.copy()
            else:
                A = arg1.tolil()

            if dtype is not None:
                A = A.astype(dtype)

            self.shape = A.shape
            self.dtype = A.dtype
            self.rows  = A.rows
            self.data  = A.data
        elif isinstance(arg1,tuple):
            if isshape(arg1):
                if shape is not None:
                    raise ValueError('invalid use of shape parameter')
                M, N = arg1
                self.shape = (M,N)
                self.rows = np.empty((M,), dtype=object)
                self.data = np.empty((M,), dtype=object)
                for i in range(M):
                    self.rows[i] = []
                    self.data[i] = []
            else:
                raise TypeError('unrecognized lil_matrix constructor usage')
        else:
            #assume A is dense
            try:
                A = np.asmatrix(arg1)
            except TypeError:
                raise TypeError('unsupported matrix type')
            else:
                from .csr import csr_matrix
                A = csr_matrix(A, dtype=dtype).tolil()

                self.shape = A.shape
                self.dtype = A.dtype
                self.rows  = A.rows
                self.data  = A.data

    def __iadd__(self,other):
        self[:,:] = self + other
        return self

    def __isub__(self,other):
        self[:,:] = self - other
        return self

    def __imul__(self,other):
        if isscalarlike(other):
            self[:,:] = self * other
            return self
        else:
            raise NotImplementedError

    def __itruediv__(self,other):
        if isscalarlike(other):
            self[:,:] = self / other
            return self
        else:
            raise NotImplementedError

    # Whenever the dimensions change, empty lists should be created for each
    # row

    def getnnz(self):
        return sum([len(rowvals) for rowvals in self.data])
    nnz = property(fget=getnnz)

    def __str__(self):
        val = ''
        for i, row in enumerate(self.rows):
            for pos, j in enumerate(row):
                val += "  %s\t%s\n" % (str((i, j)), str(self.data[i][pos]))
        return val[:-1]

    def getrowview(self, i):
        """Returns a view of the 'i'th row (without copying).
        """
        new = lil_matrix((1, self.shape[1]), dtype=self.dtype)
        new.rows[0] = self.rows[i]
        new.data[0] = self.data[i]
        return new

    def getrow(self, i):
        """Returns a copy of the 'i'th row.
        """
        new = lil_matrix((1, self.shape[1]), dtype=self.dtype)
        new.rows[0] = self.rows[i][:]
        new.data[0] = self.data[i][:]
        return new

    def _get1(self, i, j):

        if i < 0:
            i += self.shape[0]
        if i < 0 or i >= self.shape[0]:
            raise IndexError('row index out of bounds')

        if j < 0:
            j += self.shape[1]
        if j < 0 or j >= self.shape[1]:
            raise IndexError('column index out of bounds')

        row  = self.rows[i]
        data = self.data[i]

        pos = bisect_left(row, j)
        if pos != len(data) and row[pos] == j:
            return self.dtype.type(data[pos])
        else:
            return self.dtype.type(0)

    def _slicetoseq(self, j, shape):
        step = j.step or 1
        if j.start is not None and j.start < 0:
            start =  shape + j.start
        elif j.start is None:
            if step > 0:
                start = 0
            else:
                start = shape
        else:
            start = j.start
        if j.stop is not None and j.stop < 0:
            stop = shape + j.stop
        elif j.stop is None:
            if step > 0:
                stop = shape
            else:
                stop = -1
        else:
            stop = j.stop
        j = list(range(start, stop, step))
        return j


    def __getitem__(self, index):
        """Return the element(s) index=(i, j), where j may be a slice.
        This always returns a copy for consistency, since slices into
        Python lists return copies.
        """
        try:
            i, j = index
        except (AssertionError, TypeError):
            if isinstance(index, (list, np.ndarray, slice)):
                i = index
                j = slice(None)
            else:
                raise IndexError('invalid index')

        if not np.isscalar(i) and np.isscalar(j):
            warn('Indexing into a lil_matrix with multiple indices is slow. '
                 'Pre-converting to CSC or CSR beforehand is more efficient.',
                 SparseEfficiencyWarning)

        # Indicator variable so that 1 element slices generate matrices
        slicemat=0
        if isinstance(i, slice) or isinstance(j, slice):
            slicemat=1
            if isinstance(i, slice):
                i = self._slicetoseq(i, self.shape[0])
                if not i:
                    return
            i = np.atleast_1d(i)
            if isinstance(j, slice):
                j = self._slicetoseq(j, self.shape[1])
                if not j:
                    return
            j = np.atleast_1d(j)
            if i.ndim>1 or j.ndim>1:
                raise IndexError('indices can only return 2-d matrix')
            i = np.outer(i, np.ones(j.shape[0], dtype=int))
            j = np.vstack([j]*i.shape[0])
        else:
            i = np.atleast_2d(i)
            j = np.atleast_2d(j)
        # Make i and j into same shape
            if j.shape==i.shape:
                pass
            elif i.shape==(1, 1):
                i = i[0][0]*np.ones(j.shape, dtype=int)
            elif j.shape==(1, 1):
                j = j[0][0]*np.ones(i.shape, dtype=int)
            elif i.shape[1]==j.shape[1]:
                if i.shape[0]==1:
                    i = np.vstack([i]*j.shape[0])
                elif j.shape[0]==1:
                    j = np.vstack([j]*i.shape[0])
                else:
                    raise ValueError('shape mismatch: objects cannot be '+\
                                         'broadcast to a single shape')
            else:
                raise ValueError('shape mismatch: objects cannot be '+\
                                     'broadcast to a single shape')
        if i.shape==j.shape and i.shape==(1, 1) and not slicemat:
            return self._get1(i[0, 0], j[0, 0])
        return self.__class__([[self._get1(i[ii, jj], j[ii, jj]) for jj in 
                                xrange(i.shape[1])] for ii in 
                               xrange(i.shape[0])])

    def _insertat2(self, row, data, j, x):
        """ helper for __setitem__: insert a value in the given row/data at
        column j. """

        if j < 0: #handle negative column indices
            j += self.shape[1]

        if j < 0 or j >= self.shape[1]:
            raise IndexError('column index out of bounds')

        if not np.isscalar(x):
            raise ValueError('setting an array element with a sequence')

        try:
            x = self.dtype.type(x)
        except:
            raise TypeError('Unable to convert value (%s) to dtype [%s]' % (x,self.dtype.name))

        pos = bisect_left(row, j)
        if x != 0:
            if pos == len(row):
                row.append(j)
                data.append(x)
            elif row[pos] != j:
                row.insert(pos, j)
                data.insert(pos, x)
            else:
                data[pos] = x
        else:
            if pos < len(row) and row[pos] == j:
                del row[pos]
                del data[pos]

    def __setitem__(self, index, x):
        try:
            i, j = index
        except (ValueError, TypeError):
            if isinstance(index, (list, np.ndarray, slice)):
                i = index
                j = slice(None)
            else:
                raise IndexError('invalid index')

        # shortcut for common case of full matrix assign:
        if (isspmatrix(x) and isinstance(i, slice) and i == slice(None) and
            isinstance(j, slice) and j == slice(None)):
            x = lil_matrix(x, dtype=self.dtype)
            self.rows = x.rows
            self.data = x.data
            return

        # Transform data into numpy arrays to enable ravel()
        if isinstance(i, slice) or isinstance(j, slice):
            if isinstance(i, slice):
                i = self._slicetoseq(i, self.shape[0])
                if not i:
                    return
            i = np.atleast_1d(i).ravel()
            if isinstance(j, slice):
                j = self._slicetoseq(j, self.shape[1])
                if not j:
                    return
            j = np.atleast_1d(j).ravel()
            i = np.outer(i, np.ones(j.shape[0], dtype=int))
            j = np.vstack([j]*i.shape[0])
        else:
            i = np.atleast_2d(i)
            j = np.atleast_2d(j)
        # Make i and j into same shape
            if j.shape==i.shape:
                pass
            elif i.shape==(1, 1):
                i = i[0][0]*np.ones(j.shape, dtype=int)
            elif j.shape==(1, 1):
                j = j[0][0]*np.ones(i.shape, dtype=int)
            elif i.shape[1]==j.shape[1]:
                if i.shape[0]==1:
                    i = np.vstack([i]*j.shape[0])
                elif j.shape[0]==1:
                    j = np.vstack([j]*i.shape[0])
                else:
                    raise ValueError('shape mismatch: objects cannot be '+\
                                         'broadcast to a single shape')
            else:
                raise ValueError('shape mismatch: objects cannot be '+\
                                     'broadcast to a single shape')

        # If input is a sparse matrix, handle separately
        if isspmatrix(x):
            if x.shape==(1, 1):
                for ii, jj in zip(i.ravel(), j.ravel()):
                    self._insertat2(self.rows[ii], self.data[ii], 
                                    j[jj], x[0, 0])
                return
            elif x.shape==i.shape:
                for ii, jj, xx in zip(i.ravel(), j.ravel(), 
                                      x.toarray().ravel()):
                    self._insertat2(self.rows[ii], self.data[ii], jj, xx)
                return
            elif x.shape[1]==i.shape[1] and x.shape[0]==1:
                for ii, jj in zip(i.ravel(), j.ravel(), 
                                  np.concatenat([x.toarry()]*i.shape[1])):
                    self._insertat2(self.rows[ii], self.data[ii], jj, xx)
                return
            else:
                raise ValueError('shape mismatch: objects cannot be '+\
                                     'broadcast to a single shape')

        x = np.atleast_2d(np.asarray(x, dtype=self.dtype))
        # Shortcut for scalar x
        if x.shape==(1, 1):
            for ii, jj in zip(i.ravel(), j.ravel()):
                self._insertat2(self.rows[ii], self.data[ii], 
                                jj, x[0, 0])
            return
        # Make x and i into the same shape
        if i.shape==x.shape:
            pass
        elif x.shape[1]==i.shape[1] and x.shape[0]==1:
            x = np.vstack([x]*i.shape[0])
        else:
            raise ValueError('shape mismatch: objects cannot be '+\
                                 'broadcast to a single shape')
        # Set values
        for ii, jj, xx in zip(i.ravel(), j.ravel(), x.ravel()):
            self._insertat2(self.rows[ii], self.data[ii], jj, xx)


    def _mul_scalar(self, other):
        if other == 0:
            # Multiply by zero: return the zero matrix
            new = lil_matrix(self.shape, dtype=self.dtype)
        else:
            new = self.copy()
            # Multiply this scalar by every element.
            new.data[:] = [[val*other for val in rowvals] for
                           rowvals in new.data]
        return new

    def __truediv__(self, other):           # self / other
        if isscalarlike(other):
            new = self.copy()
            # Divide every element by this scalar
            new.data = [[val/other for val in rowvals] for
                        rowvals in new.data]
            return new
        else:
            return self.tocsr() / other

## This code doesn't work with complex matrices
#    def multiply(self, other):
#        """Point-wise multiplication by another lil_matrix.
#
#        """
#        if np.isscalar(other):
#            return self.__mul__(other)
#
#        if isspmatrix_lil(other):
#            reference,target = self,other
#
#            if reference.shape != target.shape:
#                raise ValueError("Dimensions do not match.")
#
#            if len(reference.data) > len(target.data):
#                reference,target = target,reference
#
#            new = lil_matrix(reference.shape)
#            for r,row in enumerate(reference.rows):
#                tr = target.rows[r]
#                td = target.data[r]
#                rd = reference.data[r]
#                L = len(tr)
#                for c,column in enumerate(row):
#                    ix = bisect_left(tr,column)
#                    if ix < L and tr[ix] == column:
#                        new.rows[r].append(column)
#                        new.data[r].append(rd[c] * td[ix])
#            return new
#        else:
#            raise ValueError("Point-wise multiplication only allowed "
#                             "with another lil_matrix.")

    def copy(self):
        from copy import deepcopy
        new = lil_matrix(self.shape, dtype=self.dtype)
        new.data = deepcopy(self.data)
        new.rows = deepcopy(self.rows)
        return new

    def reshape(self,shape):
        new = lil_matrix(shape, dtype=self.dtype)
        j_max = self.shape[1]
        for i,row in enumerate(self.rows):
            for col,j in enumerate(row):
                new_r,new_c = np.unravel_index(i*j_max + j,shape)
                new[new_r,new_c] = self[i,j]
        return new

    def toarray(self, order=None, out=None):
        """See the docstring for `spmatrix.toarray`."""
        d = self._process_toarray_args(order, out)
        for i, row in enumerate(self.rows):
            for pos, j in enumerate(row):
                d[i, j] = self.data[i][pos]
        return d

    def transpose(self):
        return self.tocsr().transpose().tolil()

    def tolil(self, copy=False):
        if copy:
            return self.copy()
        else:
            return self

    def tocsr(self):
        """ Return Compressed Sparse Row format arrays for this matrix.
        """

        indptr = np.asarray([len(x) for x in self.rows], dtype=np.intc)
        indptr = np.concatenate( (np.array([0], dtype=np.intc), np.cumsum(indptr)) )

        nnz = indptr[-1]

        indices = []
        for x in self.rows:
            indices.extend(x)
        indices = np.asarray(indices, dtype=np.intc)

        data = []
        for x in self.data:
            data.extend(x)
        data = np.asarray(data, dtype=self.dtype)

        from .csr import csr_matrix
        return csr_matrix((data, indices, indptr), shape=self.shape)

    def tocsc(self):
        """ Return Compressed Sparse Column format arrays for this matrix.
        """
        return self.tocsr().tocsc()


def isspmatrix_lil( x ):
    return isinstance(x, lil_matrix)
