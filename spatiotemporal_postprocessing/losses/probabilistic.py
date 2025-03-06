import torch 
import torch.nn as nn
import scoringrules as sr
import mlflow

class MaskedCRPSNormal(nn.Module):
    
    def __init__(self):
        super(MaskedCRPSNormal, self).__init__()
        
    def forward(self, pred, y):
        mask = ~torch.isnan(y)
        y = y[mask]
        mu = pred.loc[mask].flatten()
        sigma = pred.scale[mask].flatten()
        
        normal = torch.distributions.Normal(torch.zeros_like(mu), torch.ones_like(sigma))
        
        scaled = (y - mu) / sigma
        
        Phi = normal.cdf(scaled)
        phi = torch.exp(normal.log_prob(scaled))
        
        crps = sigma * (scaled * (2 * Phi - 1) + 2 * phi - (1 / torch.sqrt(torch.tensor(torch.pi, device=sigma.device))))

        return crps.mean()
    
class MaskedCRPSLogNormal(nn.Module):
    
    def __init__(self):
        super(MaskedCRPSLogNormal, self).__init__()
        self.i = 0
        
    def forward(self, pred, y):
        mask = ~torch.isnan(y)
        
        y = y[mask]
        eps = 1e-5
        y += eps  # Avoid 0s (pdf(y=0) is undefined for  Y~LogNormal )
        
        mu = pred.loc[mask].flatten()
        sigma = pred.scale[mask].flatten()
        
        normal = torch.distributions.Normal(torch.zeros_like(mu), torch.ones_like(sigma))
        
        # Source: Baran and Lerch (2015) Log‐normal distribution based Ensemble Model Output Statistics models for probabilistic wind‐speed forecasting
        omega = (torch.log(y)-mu)/sigma
        
        ex_input = mu + (sigma**2)/2
        
        # Clamp exponential for stability (e^15 = 3269017)
        # Note that the true mean of the Log-Normal is E[Y]=exp(mu+sigma^2/2), Y~LogN(mu,sigma)
        # This means that clamping this value still leaves room for a huge range of values
        # (Definitely enough for the wind speed :P)
        ex_input = torch.clamp(ex_input, max=15)
        mlflow.log_metric('exp_input_debug', (ex_input).max(), step=self.i)
        self.i += 1 
        
        ex = 2*torch.exp(ex_input)
        
        crps = y * (2*normal.cdf(omega)-1.0) - ex * (normal.cdf(omega-sigma)+normal.cdf(sigma/(2**0.5))-1.0)
        
        return crps.mean()
    
    
class MaskedCRPSEnsemble(nn.Module):
    
    def __init__(self):
        super(MaskedCRPSEnsemble, self).__init__()
        
    def forward(self, samples, y):
        # Pattern of y := [batch, time, station]
        # Patter of samples := [batch, time, station, sample]
        
        mask = ~torch.isnan(y)
        
        losses = sr.crps_ensemble(y.squeeze(-1), samples.squeeze(-1))
        
        return losses[mask.squeeze(1)].mean()