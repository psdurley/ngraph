#!/usr/bin/env python
# ----------------------------------------------------------------------------
# Copyright 2017 Nervana Systems Inc.
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ----------------------------------------------------------------------------
from contextlib import closing
import ngraph as ng
from ngraph.frontends.neon import (Layer, Sequential, Preprocess, LSTM,
                                   Affine, Softmax, Tanh, Logistic)
from ngraph.frontends.neon import UniformInit, RMSProp
from ngraph.frontends.neon import ax, loop_train
from ngraph.frontends.neon import NgraphArgparser, make_bound_computation, make_default_callbacks
from ngraph.frontends.neon import SequentialArrayIterator
import ngraph.transformers as ngt

from ngraph.frontends.neon import PTB

# parse the command line arguments
parser = NgraphArgparser(__doc__)
parser.add_argument('--layer_type', default='lstm', choices=['lstm'],
                    help='type of recurrent layer to use (lstm)')
parser.set_defaults()
args = parser.parse_args()

# these hyperparameters are from the paper
args.batch_size = 64
time_steps = 50
hidden_size = 128
gradient_clip_value = 5

# download penn treebank
tree_bank_data = PTB(path=args.data_dir)
ptb_data = tree_bank_data.load_data()
train_set = SequentialArrayIterator(ptb_data['train'], batch_size=args.batch_size,
                                    time_steps=time_steps, total_iterations=args.num_iterations)

valid_set = SequentialArrayIterator(ptb_data['valid'], batch_size=args.batch_size,
                                    time_steps=time_steps)

inputs = train_set.make_placeholders()
ax.Y.length = len(tree_bank_data.vocab)


def expand_onehot(x):
    return ng.one_hot(x, axis=ax.Y)


# weight initialization
init = UniformInit(low=-0.08, high=0.08)

if args.layer_type == "lstm":
    rlayer = LSTM(hidden_size, init, activation=Tanh(),
                  gate_activation=Logistic(), return_sequence=True)

# model initialization
seq1 = Sequential([Preprocess(functor=expand_onehot),
                   rlayer,
                   Affine(init, activation=Softmax(), bias_init=init, axes=(ax.Y,))])

optimizer = RMSProp(gradient_clip_value=gradient_clip_value)

train_prob = seq1(inputs['inp_txt'])
train_loss = ng.cross_entropy_multi(train_prob,
                                    ng.one_hot(inputs['tgt_txt'], axis=ax.Y),
                                    usebits=True)
batch_cost = ng.sequential([optimizer(train_loss), ng.mean(train_loss, out_axes=())])
train_outputs = dict(batch_cost=batch_cost)

with Layer.inference_mode_on():
    inference_prob = seq1(inputs['inp_txt'])
eval_loss = ng.cross_entropy_multi(inference_prob,
                                   ng.one_hot(inputs['tgt_txt'], axis=ax.Y),
                                   usebits=True)
eval_outputs = dict(cross_ent_loss=eval_loss)

# Now bind the computations we are interested in
with closing(ngt.make_transformer()) as transformer:
    train_computation = make_bound_computation(transformer, train_outputs, inputs)
    loss_computation = make_bound_computation(transformer, eval_outputs, inputs)

    cbs = make_default_callbacks(output_file=args.output_file,
                                 frequency=args.iter_interval,
                                 train_computation=train_computation,
                                 total_iterations=args.num_iterations,
                                 eval_set=valid_set,
                                 loss_computation=loss_computation,
                                 use_progress_bar=args.progress_bar)

    loop_train(train_set, train_computation, cbs)
