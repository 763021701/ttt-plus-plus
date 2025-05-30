from copy import deepcopy

import torch
import torch.nn as nn
import torch.jit
import torch.optim as optim
import torch.nn.functional as F

class BNM(nn.Module):
    """BNM adapts a model by batch nuclear minimization during testing.
    Once BNMed, a model adapts itself by updating on every forward.
    """
    def __init__(self, model, optimizer, steps=1, episodic=False):
        super().__init__()
        self.model = model
        self.optimizer = optimizer
        self.steps = steps
        assert steps > 0, "BNM requires >= 1 step(s) to forward and update"
        self.episodic = episodic

        # note: if the model is never reset, like for continual adaptation,
        # then skipping the state copy would save memory
        self.model_state, self.optimizer_state = \
            copy_model_and_optimizer(self.model, self.optimizer)

    def forward(self, x):
        if self.episodic:
            self.reset()

        for _ in range(self.steps):
            forward_and_adapt(x, self.model, self.optimizer)

        outputs = forward_only(x, self.model)

        return outputs

    def reset(self):
        if self.model_state is None or self.optimizer_state is None:
            raise Exception("cannot reset without saved model/optimizer state")
        load_model_and_optimizer(self.model, self.optimizer,
                                 self.model_state, self.optimizer_state)


# @torch.jit.script
# def softmax_entropy(x: torch.Tensor) -> torch.Tensor:
#     """Entropy of softmax distribution from logits."""
#     return -(x.softmax(1) * x.log_softmax(1)).sum(1)

@torch.jit.script
def batch_nuclear_norm(x: torch.Tensor) -> torch.Tensor:
    """Nuclear norm of output matrix."""
    target_softmax = F.softmax(x, dim=1)
    #return -torch.norm(target_softmax,'nuc')/target_softmax.shape[0]
    return -torch.sqrt(torch.mean(torch.svd(target_softmax)[1]**2))

@torch.enable_grad()  # ensure grads in possible no grad context for testing
def forward_and_adapt(x, model, optimizer):
    """Forward and adapt model on batch of data.
    Measure Nuclear normalization of the model prediction, take gradients, and update params.
    """
    model.train() ## !!
    # forward
    outputs = model(x)
    # adapt
    loss = batch_nuclear_norm(outputs)
    loss.backward()
    optimizer.step()
    optimizer.zero_grad()
    return outputs

def forward_only(x, model):
    """Forward model on batch of data.
    """
    model.eval()
    with torch.no_grad():
        # forward
        outputs = model(x)
    return outputs


def collect_params(model, bn_only=True):
    """
    Collect parameters from the model.
    If bn_only is True, collect only the affine scale + shift parameters from batch norms.
    If bn_only is False, collect all parameters from the model.

    Walk the model's modules and collect the specified parameters.
    Return the parameters and their names.
    Note: other choices of parameterization are possible!
    """
    params = []
    names = []

    if bn_only:
        # Collect only BatchNorm parameters
        for nm, m in model.named_modules():
            if isinstance(m, nn.BatchNorm2d):
                for np, p in m.named_parameters():
                    if np in ['weight', 'bias']:  # weight is scale, bias is shift
                        params.append(p)
                        names.append(f"{nm}.{np}")
    else:
        # Collect all parameters
        for nm, p in model.named_parameters():
            params.append(p)
            names.append(nm)

    return params, names


def copy_model_and_optimizer(model, optimizer):
    """Copy the model and optimizer states for resetting after adaptation."""
    model_state = deepcopy(model.state_dict())
    optimizer_state = deepcopy(optimizer.state_dict())
    return model_state, optimizer_state


def load_model_and_optimizer(model, optimizer, model_state, optimizer_state):
    """Restore the model and optimizer states from copies."""
    model.load_state_dict(model_state, strict=True)
    optimizer.load_state_dict(optimizer_state)


def configure_model(model):
    """Configure model for use with BNM."""
    # train mode, because BNM optimizes the model to minimize entropy
    model.train()
    # disable grad, to (re-)enable only what BNM updates
    model.requires_grad_(False)
    # configure norm for BNM updates: enable grad + force batch statisics
    for m in model.modules():
        if isinstance(m, nn.BatchNorm2d):
            m.requires_grad_(True)
            # force use of batch stats in train and eval modes
            m.track_running_stats = False
            m.running_mean = None
            m.running_var = None
    return model


def check_model(model):
    """Check model for compatability with BNM."""
    is_training = model.training
    assert is_training, "BNM needs train mode: call model.train()"
    param_grads = [p.requires_grad for p in model.parameters()]
    has_any_params = any(param_grads)
    has_all_params = all(param_grads)
    assert has_any_params, "BNM needs params to update: " \
                           "check which require grad"
    assert not has_all_params, "BNM should not update all params: " \
                               "check which require grad"
    has_bn = any([isinstance(m, nn.BatchNorm2d) for m in model.modules()])
    assert has_bn, "BNM needs normalization for its optimization"

def setup_bnm(model, args):
    """Set up BNM adaptation.
    Configure the model for training + feature modulation by batch statistics,
    collect the parameters for feature modulation by gradient optimization,
    set up the optimizer, and then BNM the model.
    """
    model = configure_model(model)
    params, param_names = collect_params(model, False)
    optimizer = setup_optimizer(params, args)
    bnm_model = BNM(model, optimizer,
                      steps=1,
                      episodic=False)
    # print(f"model for adaptation: %s", model)
    # print(f"params for adaptation: %s", param_names)
    # print(f"optimizer for adaptation: %s", optimizer)
    return bnm_model

def setup_optimizer(params, args):
    """Set up optimizer for BNM adaptation.
    BNM needs an optimizer for test-time entropy minimization.
    In principle, BNM could make use of any gradient optimizer.
    In practice, we advise choosing Adam or SGD+momentum.
    For optimization settings, we advise to use the settings from the end of
    trainig, if known, or start with a low learning rate (like 0.001) if not.
    For best results, try tuning the learning rate and batch size.
    """
    return optim.Adam(params,
                      lr=args.lr,
                      betas=(0.9, 0.999),
                      weight_decay=0.)
