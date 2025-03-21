import nibabel as nib
import numpy as np
import dicom2nifti as d2n
from scipy.ndimage import zoom, gaussian_filter
from arraythings import downsample_array


def load(nii_path):
    """Loads a NIfTI image file from the specified file path.

    Parameters:
    -----------
    nii_path : str
        Path to the NIfTI file.

    Returns:
    --------
    nibabel.Nifti1Image
        Loaded NIfTI image, containing the image data as a NumPy array and the associated affine matrix.
    """

    img = nib.load(nii_path)
    return nib.Nifti1Image(np.asarray(img.dataobj), img.affine)


def reorient_nifti(image, output_orientation="LPS"):
    """Reorients a NIfTI image to the specified output orientation.

    Parameters:
    -----------
    image : nibabel.Nifti1Image
        The input NIfTI image to be reoriented.
    output_orientation : str, optional
        The desired output orientation code in the form of "LPS", "RAS", etc.
        Default is "LPS".

    Returns:
    --------
    reoriented_image : nibabel.Nifti1Image
        The reoriented 3D NIfTI image.
    """

    ornt = nib.orientations.axcodes2ornt(nib.orientations.aff2axcodes(image.affine))
    ornt_ = nib.orientations.axcodes2ornt(output_orientation)
    return image.as_reoriented(nib.orientations.ornt_transform(ornt, ornt_))


def resample_nifti(input_nii, output_zooms, order=3, prefilter=True, reference_nii=None):
    """Resamples a Nifti image to have new voxel sizes defined by `output_zooms`.

    Parameters
    ----------
    input_nii : nibabel.nifti1.Nifti1Image
        The input Nifti image to resample.
    output_zooms : tuple
        The desired voxel size for the resampled Nifti image. It must be a tuple or list of same length as the number of dimensions in the original Nifti image. None can be used to specify that a certain dimension does not need to be resampled.
    order : int or str, optional
        The order of interpolation (0 to 5) or the string 'mean' to perform a downsampling based on mean (with a moving average window that gets the effective output zooms as close as possible to the requested output zooms). Default is 3.
    prefilter : bool, optional
        Whether to apply a Gaussian filter to the input data before resampling (https://stackoverflow.com/questions/35340197/box-filter-size-in-relation-to-gaussian-filter-sigma). Default is True.
    reference_nii : nibabel.nifti1.Nifti1Image or None, optional
        If not None, the resampled Nifti image will have the same dimensions as `reference_nii`. Default is None.
        E.g., when doing upsampling back to an original image space we want to make sure the image sizes are consistent. By giving a reference Nifti image, we crop or pad with zeros where necessary.

    Returns
    -------
    output_nii : nibabel.nifti1.Nifti1Image
        The resampled Nifti image.
    """

    input_zooms = input_nii.header.get_zooms()
    assert len(input_zooms) == len(output_zooms), "Number of dimensions mismatch."
    assert np.allclose(input_zooms[:3], np.linalg.norm(input_nii.affine[:3, :3], 2, axis=0)), "Inconsistency (we only support voxel size = voxel distance) in affine and zooms (spatial) of input Nifti image."
    input_array = input_nii.get_fdata()
    output_zooms = [input_zoom if output_zoom is None else output_zoom for input_zoom, output_zoom in zip(input_zooms, output_zooms)]
    if order == "mean":
        assert all([4 / 3 * output_zoom >= input_zoom for output_zoom, input_zoom in zip(output_zooms, input_zooms)]), "This function with order='mean' only supports downsampling by an integer factor (input zooms: {}).".format(input_zooms)
        zoom_factors = [1 if input_zoom > 2 / 3 * output_zoom else 1 / int(round(output_zoom / input_zoom)) for input_zoom, output_zoom in zip(input_zooms, output_zooms)]
        output_zooms = [input_zoom / zoom_factor for input_zoom, zoom_factor in zip(input_zooms, zoom_factors)]
        output_array = downsample_array(input_array, window_sizes=[int(1 / zoom_factor) for zoom_factor in zoom_factors])

    else:
        assert isinstance(order, int), "When order != 'mean', it must be an integer (see scipy.ndimage.zoom)."
        zoom_factors = [input_zoom / output_zoom for input_zoom, output_zoom in zip(input_zooms, output_zooms)]
        if prefilter:
            input_array = gaussian_filter(input_array.astype(np.float32), [np.sqrt(((1 / zoom_factor)**2 - 1) / 12) if zoom_factor < 1 else 0 for zoom_factor in zoom_factors], mode="nearest")

        output_array = zoom(input_array, zoom_factors, order=order, mode="nearest")

    if reference_nii is not None:
        assert np.allclose(output_zooms, reference_nii.header.get_zooms()), "The output zooms are not equal to the reference zooms."
        output_array_ = np.zeros_like(reference_nii.get_fdata())
        output_array_[tuple([slice(min(s, s_)) for s, s_ in zip(output_array.shape, output_array_.shape)])] = output_array[tuple([slice(min(s, s_)) for s, s_ in zip(output_array.shape, output_array_.shape)])]
        output_array = output_array_
        output_affine = reference_nii.affine

    else:
        output_affine = input_nii.affine.copy()
        output_affine[:3, :3] = output_affine[:3, :3] / zoom_factors[:3]

    output_nii = nib.Nifti1Image(output_array, affine=output_affine)
    output_nii.header.set_zooms(output_zooms)  # important to set non-spatial zooms correctly
    return output_nii


def orthogonalize_nifti(image, resample_padding=0, resample_spline_interpolation_order=0):
    """Orthogonalizes the given NIfTI image using dicom2nifti's resampling methods, adjusting the padding and interpolation settings temporarily for this operation.

    Parameters:
    -----------
    image : nibabel.Nifti1Image
        The NIfTI image to be orthogonalized.
    resample_padding : int, optional
        Padding value used during resampling. Default is 0.
    resample_spline_interpolation_order : int, optional
        Spline interpolation order used during resampling. Default is 0.

    Returns:
    --------
    list of nibabel.Nifti1Image
        A list containing the orthogonalized NIfTI image.
    """
        
    d2n.settings.set_resample_padding(resample_padding)
    d2n.settings.set_resample_spline_interpolation_order(resample_spline_interpolation_order)
    orthogonal_nii = d2n.resample.resample_nifti_images([image])
    d2n.settings.set_resample_spline_interpolation_order(0)  # back to default
    d2n.settings.set_resample_padding(0)  # back to default
    return orthogonal_nii


def get_angles_between_axes(affine, in_degrees=True):
    """Calculates the angles between the axes of an affine transformation matrix.

    Parameters:
    -----------
    affine : np.ndarray
        A 4x4 affine transformation matrix.
    in_degrees : bool, optional
        Flag to determine if the output angles should be in degrees (True) or radians (False). Default is True.

    Returns:
    --------
    tuple
        A tuple containing the angles between the x-y, x-z, and y-z axes.
    """
        
    assert affine.shape == (4, 4)
    xy = np.arccos(np.sum(affine[:, 0] * affine[:, 1]) / (np.linalg.norm(affine[:, 0]) * np.linalg.norm(affine[:, 1])))
    xz = np.arccos(np.sum(affine[:, 0] * affine[:, 2]) / (np.linalg.norm(affine[:, 0]) * np.linalg.norm(affine[:, 2])))
    yz = np.arccos(np.sum(affine[:, 1] * affine[:, 2]) / (np.linalg.norm(affine[:, 1]) * np.linalg.norm(affine[:, 2])))
    if in_degrees:
        xy = xy * 180 / np.pi
        xz = xz * 180 / np.pi
        yz = yz * 180 / np.pi
    
    return xy, xz, yz
    

def is_orthogonal_affine(affine, max_allowed_angles_in_degrees=(1, 1, 1)):
    """Checks if the affine transformation matrix is nearly orthogonal by comparing the angles between its axes against specified maximum allowed angles.

    Parameters:
    -----------
    affine : np.ndarray
        A 4x4 affine transformation matrix.
    max_allowed_angles_in_degrees : tuple, optional
        Maximum allowed deviation angles in degrees for the matrix to be considered orthogonal. Default is (1, 1, 1).

    Returns:
    --------
    bool
        True if the matrix is nearly orthogonal within the specified angle tolerances, otherwise False.
    """

    xy, xz, yz = get_angles_between_axes(affine)
    return np.abs(90 - xy) <= max_allowed_angles_in_degrees[0] and np.abs(90 - xz) <= max_allowed_angles_in_degrees[1] and np.abs(90 - yz) <= max_allowed_angles_in_degrees[2]
