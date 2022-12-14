import torch
import numpy as np

from utils.diffusionDataset import get_alpha_bar


def reconstruct_image_from_noise(noisy_image, noise, t, variance_schedule):
    """Reconstruct the image given the noisy image and the noise.

    Parameters
    ----------
    noisy_image : 3D numpy array
    noise : 3D numpy array
    t : int
        timestep.
    variance_schedule : array or array-like
        sequence of beta_t.

    Returns
    -------
    array
        original image
    """
    alpha_bar = get_alpha_bar(variance_schedule)[t]
    return (noisy_image - noise*np.sqrt(1-alpha_bar))/np.sqrt(alpha_bar).clip(0, 1)


def reconstruct_single_step(net, noisy_image, t, variance_schedule, device=None):
    """Obsolete: use reconstruct(step=t)
    Reconstruct the image in a single step.

    Parameters
    ----------
    net : ``torch.nn.Module``
        the model that must reconstruct the image.
    noisy_image : 3D numpy array
            its shape must be ``(n_channels, spatial_1, spatial_2)``. Only a single image is
            processed, the batch dimension must be dropped.
    t : int
        timestep.
    variance_schedule : array or array-like
        sequence of beta_t.
    device : ``torch.device``, optional
        by default 'cpu'.

    Returns
    -------
    3D numpy array
        reconstructed image with shape ``(n_channels, spatial_1, spatial_2)``.
    """
    if device is None:
        device = torch.device('cpu')
    net.to(device)

    net.eval()      # set net to evaluation mode

    noisy_image_batch = torch.Tensor(noisy_image).reshape(1, *noisy_image.shape)
    t_batch = torch.Tensor([t])
    with torch.no_grad():
        noisy_image_device = noisy_image_batch.to(device)
        t_device = t_batch.to(device)
        pred_noise_device = net(noisy_image_device, t_device)

    pred_noise = pred_noise_device.detach().cpu().numpy()[0]

    alpha_bar = get_alpha_bar(variance_schedule)[t]
    rec_single_step = (noisy_image - pred_noise*np.sqrt(1-alpha_bar))/np.sqrt(alpha_bar).clip(0, 1)
    

    if 'cuda' in device.type:
        # free gpu memory
        del noisy_image_device
        del t_device
        del pred_noise_device
        torch.cuda.empty_cache()

    return rec_single_step.clip(0, 1)


def reconstruct(net, noisy_image, t, variance_schedule, step_size, overstep=0.5, sigma=None, return_sequences=False, device=None):
    """Reconstruct the image with variable number of steps.

    Parameters
    ----------
    net : ``torch.nn.Module``
        the model that must reconstruct the image.
    noisy_image : 3D numpy array
            its shape must be ``(n_channels, spatial_1, spatial_2)``. Only a single image is
            processed, the batch dimension must be dropped.
    t : int, 
        timestep.
    variance_schedule : array or array-like
        sequence of beta_t.
    step_size : int,
        the number of original timesteps equivalent to the reconstruct timestep.
    overstep : float, optional
        correction factor to the predicted noise. For more info, see Stable diffusion paper.
        The default is 0.5.
    sigma : int or list, optional
        noise added to each reconstruction step.
    return_sequences : bool, optional
        wether to return the whole sequences or just the last reconstruction, default False.
    device : ``torch.device``, optional
        by default 'cpu'.

    Returns
    -------
    3D numpy array (or 4D numpy array if ``return_sequences`` is set to True)
        reconstructed image with shape ``(n_channels, spatial_1, spatial_2)``.
    """
    if device is None:
        device = torch.device('cpu')
    net.to(device)

    if sigma is None:
        sigma = np.zeros(t)

    if not hasattr(sigma, "__getitem__"):
        sigma = np.ones(t) * sigma

    net.eval()      # set net to evaluation mode
    
    with torch.no_grad():
        alpha_bar = torch.Tensor(get_alpha_bar(variance_schedule)).to(device)
        sigma = torch.Tensor(sigma).to(device)
        
        reconstructions = np.zeros((t//step_size,) + noisy_image.shape)
        reconstructions[0] = noisy_image.reshape(1, *noisy_image.shape)
        x = torch.Tensor(reconstructions[:1]).to(device)
        
        reconstructions=(reconstructions*255).astype(np.uint8)

        print(f'T start = {t}')
        for i in reversed(range(1, t//step_size)):
            ti = i*step_size
            print(f'Sampling: t={ti}'.ljust(50), end = '\r')
            t_tensor = torch.Tensor([ti]).to(device)
            pred_noise = net(x, t_tensor)

            f = alpha_bar[ti]/alpha_bar[ti-step_size]
            x = (x - (1+overstep)*pred_noise*(1-f)/torch.sqrt(1-alpha_bar[ti]))/torch.sqrt(f) + sigma[ti]*torch.randn(x.shape).to(device)
            torch.cuda.empty_cache()
            if return_sequences:
                reconstructions[t//step_size-i]=(x.detach().cpu().numpy().clip(0, 1)*255).astype(np.uint8)
        del t_tensor

        print('Sampling done.')
    if return_sequences:
        return reconstructions
    else:
        return x.detach().cpu().numpy()[0].clip(0, 1)


def reconstruct_sequentially(net, noisy_image, t, variance_schedule, device=None, sigma=None):
    """Obsolete: use reconstruct(step=1)
    Sampling as in Ho et. al (2020).

    Parameters
    ----------
    net : ``torch.nn.Module``
        the model that must reconstruct the image.
    noisy_image : 3D numpy array
            its shape must be ``(n_channels, spatial_1, spatial_2)``. Only a single image is
            processed, the batch dimension must be dropped.
    t : int
        timestep.
    variance_schedule : array or array-like
        sequence of beta_t.
    sigma : {int, array or array-like}, optional
        noise sequence to add at each reconstruction step.
    device : ``torch.device``, optional
        by default 'cpu'.

    Returns
    -------
    3D numpy array
        reconstructed image with shape ``(n_channels, spatial_1, spatial_2)``.
    """
    if device is None:
        device = torch.device('cpu')
    net.to(device)

    if sigma is None:
        sigma = np.zeros(t)

    if not hasattr(sigma, "__getitem__"):
        sigma = np.ones(t) * sigma

    net.eval()      # set net to evaluation mode

    with torch.no_grad():
        beta = torch.Tensor(variance_schedule).to(device)
        alpha_bar = torch.Tensor(get_alpha_bar(variance_schedule)).to(device)
        sigma = torch.Tensor(sigma).to(device)

        x = torch.Tensor(noisy_image.reshape(1, *noisy_image.shape)).to(device)

        print(f'T start = {t}')
        for ti in reversed(range(1, t)):
            print(f'Sampling: t={ti}'.ljust(50), end = '\r')
            t_tensor = torch.Tensor([ti]).to(device)
            pred_noise = net(x, t_tensor)
            x = (x - pred_noise*beta[ti]/torch.sqrt(1-alpha_bar[ti]))/torch.sqrt(1-beta[ti]) + sigma[ti]*torch.randn(x.shape).to(device)
            torch.cuda.empty_cache()
        del t_tensor

        print('Sampling done.')
    return x.detach().cpu().numpy()[0].clip(0, 1)
