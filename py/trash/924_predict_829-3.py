#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Wed Aug 29 04:17:15 2018

@author: Kazuki
"""

import numpy as np
import pandas as pd
from tqdm import tqdm
import gc, os
import sys
argv = sys.argv
sys.path.append(f'/home/{os.environ.get("USER")}/PythonLibrary')
import lgbextension as ex
import lightgbm as lgb
from multiprocessing import cpu_count
from sklearn.model_selection import GroupKFold
from sklearn.metrics import roc_auc_score
from glob import glob
import utils, utils_cat
utils.start(__file__)
#==============================================================================

SEED = 71

LOOP = 5
NFOLD = 7

SUBMIT_FILE_PATH = '../output/829-3.csv.gz'

HEAD = 600

EXE_SUBMIT = False

COMMENT = 'CV(single): 0.806418 + 0.002499 601features oof'

param = {
         'objective': 'binary',
         'metric': 'auc',
         'learning_rate': 0.01,
         'max_depth': 6,
         'num_leaves': 63,
         'max_bin': 255,
         
         'min_child_weight': 10,
         'min_data_in_leaf': 150,
         'reg_lambda': 0.5,  # L2 regularization term on weights.
         'reg_alpha': 0.5,  # L1 regularization term on weights.
         
         'colsample_bytree': 0.9,
         'subsample': 0.9,
#         'nthread': 32,
         'nthread': cpu_count(),
         'bagging_freq': 1,
         'verbose':-1,
#         'seed': SEED
         }


np.random.seed(SEED)



#==============================================================================

imp = pd.read_csv('LOG/imp_801_imp_lgb.py-2.csv')
imp.sort_values('total', ascending=False, inplace=True)

train_oof = pd.read_csv('../data/Valid_stochastic_blending_v3-2_valid_0.308rk_0.444mw1_0.248t1_0.81050CV_0.3Adv.csv').TARGET
test_oof  = pd.read_csv('../data/stochastic_blending_v3-2_0.308rk_0.444mw1_0.248t1_0.81050CV_0.3Adv.csv').TARGET


def mk_submit(HEAD=HEAD):
    features = imp.head(HEAD).feature
    
    files_tr = ('../feature/train_' + features  + '.f').tolist()
    files_te = ('../feature/test_'  + features + '.f').tolist()
    
    # =============================================================================
    # load
    # =============================================================================
    # train
    X_train = pd.concat([
                            pd.read_feather(f) for f in tqdm(files_tr, mininterval=60)
                           ], axis=1)
    X_train['oof'] = train_oof
    
    y_train = utils.read_pickles('../data/label').TARGET
    
    X_train.head().to_csv(SUBMIT_FILE_PATH.replace('.csv', '_X.csv'), 
                          index=False, compression='gzip')
    
    if X_train.columns.duplicated().sum()>0:
        raise Exception(f'duplicated!: { X_train.columns[X_train.columns.duplicated()] }')
    print('no dup :) ')
    print(f'X_train.shape {X_train.shape}')
    
    gc.collect()
    
    CAT = list( set(X_train.columns) & set(utils_cat.ALL) )
    
    COL = X_train.columns.tolist()
    
    # test
    X_test = pd.concat([
                        pd.read_feather(f) for f in tqdm(files_te, mininterval=60)
                        ], axis=1)
    X_test['oof'] = test_oof
    X_test = X_test[COL]
    
    # =============================================================================
    # groupKfold
    # =============================================================================
    sk_tbl = pd.read_csv('../data/user_id_v7.csv.gz') # TODO: check
    user_tbl = sk_tbl.user_id.drop_duplicates().reset_index(drop=True).to_frame()
    
    sub_train = pd.read_csv('../input/application_train.csv.zip', usecols=['SK_ID_CURR']).set_index('SK_ID_CURR')
    sub_train['y'] = y_train.values
    
    group_kfold = GroupKFold(n_splits=NFOLD)
    
    # =============================================================================
    # training with cv
    # =============================================================================
    model_all = []
    auc_mean = 0
    for i in range(LOOP):
        dtrain = lgb.Dataset(X_train, y_train, categorical_feature=CAT, free_raw_data=False)
        
        # shuffle fold
        ids = list(range(user_tbl.shape[0]))
        np.random.shuffle(ids)
        user_tbl['g'] = np.array(ids) % NFOLD
        sk_tbl_ = pd.merge(sk_tbl, user_tbl, on='user_id', how='left').set_index('SK_ID_CURR')
        
        sub_train['g'] = sk_tbl_.g
        folds = group_kfold.split(X_train, sub_train['y'], sub_train['g'])
        
        gc.collect()
        param['seed'] = i
        ret, models = lgb.cv(param, dtrain, 9999, folds=folds, 
                             early_stopping_rounds=100, verbose_eval=50,
                             seed=i)
        model_all += models
        auc_mean += ret['auc-mean'][-1]
    auc_mean /= LOOP
    
    result = f"CV auc-mean(feature {HEAD}): {auc_mean}"
    print(result)
    utils.send_line(result)
    
    # =============================================================================
    # predict
    # =============================================================================
    sub = pd.read_pickle('../data/sub.p')
    
    gc.collect()
    
    label_name = 'TARGET'
    
    sub[label_name] = 0
    for model in model_all:
        y_pred = model.predict(X_test)
        sub[label_name] += pd.Series(y_pred).rank()
    sub[label_name] /= len(model_all)
    sub[label_name] /= sub[label_name].max()
    sub['SK_ID_CURR'] = sub['SK_ID_CURR'].map(int)
    
    sub.to_csv(SUBMIT_FILE_PATH, index=False, compression='gzip')

    # =============================================================================
    # submission
    # =============================================================================
    if EXE_SUBMIT:
        print('submit')
        utils.submit(SUBMIT_FILE_PATH, COMMENT)

# =============================================================================
# main
# =============================================================================

mk_submit(HEAD)

#==============================================================================
utils.end(__file__)
utils.stop_instance()


