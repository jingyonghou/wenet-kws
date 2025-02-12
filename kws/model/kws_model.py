# Copyright (c) 2021 Binbin Zhang
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sys
from typing import Optional

import torch

from kws.model.cmvn import GlobalCMVN
from kws.model.subsampling import LinearSubsampling1, Conv1dSubsampling1
from kws.model.tcn import TCN, CnnBlock, DsCnnBlock
from kws.model.mdtc import MDTC
from kws.utils.cmvn import load_cmvn


class KWSModel(torch.nn.Module):
    """Our model consists of four parts:
    1. global_cmvn: Optional, (idim, idim)
    2. preprocessing: feature dimention projection, (idim, hdim)
    3. backbone: backbone or feature extractor of the whole network, (hdim, hdim)
    4. classifier: output layer or classifier of KWS model, (hdim, odim)
    """
    def __init__(
        self,
        idim: int,
        odim: int,
        hdim: int,
        global_cmvn: Optional[torch.nn.Module],
        preprocessing: Optional[torch.nn.Module],
        backbone: torch.nn.Module,
    ):
        super().__init__()
        self.idim = idim
        self.odim = odim
        self.hdim = hdim
        self.global_cmvn = global_cmvn
        self.preprocessing = preprocessing
        self.backbone = backbone
        self.classifier = torch.nn.Linear(hdim, odim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        if self.global_cmvn is not None:
            x = self.global_cmvn(x)
        if self.preprocessing:
            x = self.preprocessing(x)
        x, _ = self.backbone(x)
        x = self.classifier(x)
        x = torch.sigmoid(x)
        return x


def init_model(configs):
    cmvn = configs.get('cmvn', {})
    if 'cmvn_file' in cmvn and cmvn['cmvn_file'] is not None:
        mean, istd = load_cmvn(cmvn['cmvn_file'])
        global_cmvn = GlobalCMVN(
            torch.from_numpy(mean).float(),
            torch.from_numpy(istd).float(),
            cmvn['norm_var'],
        )
    else:
        global_cmvn = None

    input_dim = configs['input_dim']
    output_dim = configs['output_dim']
    hidden_dim = configs['hidden_dim']

    prep_type = configs['preprocessing']['type']
    if prep_type == 'linear':
        preprocessing = LinearSubsampling1(input_dim, hidden_dim)
    elif prep_type == 'cnn1d_s1':
        preprocessing = Conv1dSubsampling1(input_dim, hidden_dim)
    elif prep_type == 'none':
        preprocessing = None
    else:
        print('Unknown preprocessing type {}'.format(prep_type))
        sys.exit(1)

    backbone_type = configs['backbone']['type']
    if backbone_type == 'gru':
        num_layers = configs['backbone']['num_layers']
        backbone = torch.nn.GRU(hidden_dim,
                                hidden_dim,
                                num_layers=num_layers,
                                batch_first=True)
    elif backbone_type == 'tcn':
        # Depthwise Separable
        num_layers = configs['backbone']['num_layers']
        ds = configs['backbone'].get('ds', False)
        if ds:
            block_class = DsCnnBlock
        else:
            block_class = CnnBlock
        kernel_size = configs['backbone'].get('kernel_size', 8)
        dropout = configs['backbone'].get('drouput', 0.1)
        backbone = TCN(num_layers, hidden_dim, kernel_size, dropout,
                       block_class)
    elif backbone_type == 'mdtc':
        stack_size = configs['backbone']['stack_size']
        num_stack = configs['backbone']['num_stack']
        kernel_size = configs['backbone']['kernel_size']
        hidden_dim = configs['backbone']['hidden_dim']

        backbone = MDTC(num_stack,
                        stack_size,
                        input_dim,
                        hidden_dim,
                        kernel_size,
                        causal=True)
    else:
        print('Unknown body type {}'.format(backbone_type))
        sys.exit(1)

    kws_model = KWSModel(input_dim, output_dim, hidden_dim, global_cmvn,
                         preprocessing, backbone)
    return kws_model
