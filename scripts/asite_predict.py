#!/usr/bin/env python

## ----------------------------------------
## scikit-ribo
## ----------------------------------------
## a module for preprocessing bam files
## ----------------------------------------
## author: Han Fang
## contact: hanfang.cshl@gmail.com
## website: hanfang.github.io
## date: 1/28/2016
## ----------------------------------------

from __future__ import print_function, division
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import os
import sys
import pandas as pd
import seaborn as sns
import numpy as np
import pybedtools as pbt
import argparse
from sklearn import linear_model, cross_validation, preprocessing, svm, tree
from sklearn.metrics import roc_curve, auc
from sklearn.cross_validation import train_test_split
from sklearn.preprocessing import label_binarize
from sklearn.multiclass import OneVsRestClassifier
from sklearn.grid_search import GridSearchCV
from sklearn.ensemble import RandomForestClassifier
from sklearn.feature_selection import SelectFromModel


class VisualizeAsite:
    ''' define a class for plotting a-site location distribution
    '''
    def __init__(self, asite_fn):
        self.asite_fn = asite_fn
        self.asite_df = pd.read_table(self.asite_fn,  header=0)

    def plot(self):
        sns.set(font_scale=2)
        g0 = sns.FacetGrid(self.asite_df,
                           row="offset",
                           col="read_length",
                           margin_titles=True,
                           col_order= list(range(25,36)),
                           row_order= list(range(3)))
        bins = np.linspace(12, 21, 10)
        g0.map(plt.hist, "asite", color="steelblue", bins=bins, lw=0,normed=True)
        g0.set(xticks=[12,15,18,21])
        plt.gcf()
        plt.savefig( self.asite_fn +".asite.pdf" )
        plt.clf()

class TrainModel:
    ''' define a class for model training - a-site prediction
    '''
    def __init__(self, object, testing_fn, cds_idx_fn):
        self.traning_df = object.asite_df
        self.asite_fn = object.asite_fn
        self.df_colnames = list(self.traning_df.columns.values)
        self.df_colnames.remove("asite")
        self.X = np.array( pd.get_dummies(self.traning_df[self.df_colnames]) ) # .astype(np.int8)
        self.y = np.array( self.traning_df["asite"])
        self.testing_fn = testing_fn
        self.testing_df = pd.read_table(self.testing_fn, header=0)
        self.cds_idx_fn = cds_idx_fn
        self.cds_idx_df = pd.read_table(self.cds_idx_fn, header=0)

    def rf_fit(self):
        ## feature selection
        self.clf = RandomForestClassifier(max_features=None, n_jobs=-1)
        self.clf = self.clf.fit(self.X, self.y)
        self.importances = self.clf.feature_importances_
        self.transformer = SelectFromModel(self.clf, prefit=True, threshold=0.05)
        self.selected_X = self.transformer.transform(self.X)
        n_selected_features = self.selected_X.shape[1]
        print("[status]\tNumber of selected features:\t"+ str(n_selected_features), flush=True)

        ## define a new classifier for reduced features
        self.new_clf = RandomForestClassifier(max_features=None, n_jobs=-1)
        self.new_clf = self.new_clf.fit(self.selected_X, self.y)

        ## cross validation
        scores = cross_validation.cross_val_score(self.new_clf, self.selected_X, self.y, cv=10)
        print("[status]\tAccuracy: %0.3f (+/- %0.3f)" % (scores.mean(), scores.std() * 2), flush=True)

    def rf_importance(self):
        ## compute the std and index for the feature importance
        std = np.std([tree.feature_importances_ for tree in self.clf.estimators_],    axis=0)
        indices = np.argsort(self.importances)[::-1]

        # Plot the feature importances of the classifier
        plt.figure()
        plt.title("Feature importances")
        plt.bar(range(self.X.shape[1]), self.importances[indices],
            color=sns.xkcd_rgb["denim blue"], yerr=std[indices], align="center")
        plt.xticks(range(self.X.shape[1]), indices)
        plt.xlim([-1, 10])
        plt.ylim([0, 1])
        plt.gcf()
        plt.savefig( self.asite_fn + ".feature_importances.pdf", facecolor="white")

    def rf_predict(self):
        ## create df for testing data
        testing_df = pd.read_table(self.testing_fn,  header=0)
        testing_df_colnames = list(testing_df.columns.values)
        names_to_exclude = set(["gene_chrom", "gene_start", "gene_end", "gene_name", "chrom", "start", "end", "name", "score", "strand", "read"])
        testing_df_colnames_subset = [x for x in testing_df_colnames if x not in names_to_exclude]
        testing_X = np.array( pd.get_dummies(testing_df[testing_df_colnames_subset]) ) # .astype(np.int8)

        ## selected a subset of features and predict a-site
        selected_testing_X = self.transformer.transform(testing_X)
        testing_df["asite"] = self.new_clf.predict(selected_testing_X)
        self.testing_df_out = testing_df[["chrom", "start", "end", "name", "strand", "read", "asite",
                                     "read_length", "offset", "gene_chrom", "gene_start", "gene_end", "gene_name", "gene_strand"]]
        self.testing_df_out.to_csv(path_or_buf=self.testing_fn + '.predicted.txt', sep='\t', header=True, index=False)

    def svm_fit(self):
        ## grid search
        self.clf = svm.SVC()
        param_grid = [ { 'C': [ 0.01, 0.1, 1, 10, 100, 1000, 10000] } ]
        self.clf_gs = GridSearchCV(estimator=self.clf, param_grid=param_grid, n_jobs=-1)
        self.clf_gs.fit(self.X, self.y)
        print("[status]\t best estimator parameters: c=", self.clf_gs.best_estimator_.C, flush=True)

        ## model fitting and cross validation
        self.clf = svm.SVC( C=self.clf_gs.best_estimator_.C)
        scores = cross_validation.cross_val_score(self.clf, self.selected_X, self.y, cv=10)
        print("[status]\tAccuracy: %0.3f (+/- %0.3f)" % (scores.mean(), scores.std() * 2), flush=True)

    def roc_curve(self):
        ''' define a class for plotting multi-class roc curve
        '''
        # shuffle and split training and test sets
        self.OVR_clf = OneVsRestClassifier(self.clf)
        self.y = label_binarize(self.y, classes=[12,13,14,15,16,17,18])
        n_classes = self.y.shape[1]
        X_train, X_test, y_train, y_test = train_test_split(self.X, self.y, test_size=.5, random_state=0)
        y_score = self.OVR_clf.fit(X_train, y_train).decision_function(X_test)

        # Compute ROC curve and ROC area for each class
        fpr = dict()
        tpr = dict()
        roc_auc = dict()
        for i in range(n_classes):
            fpr[i], tpr[i], _ = roc_curve(y_test[:, i], y_score[:, i])
            roc_auc[i] = auc(fpr[i], tpr[i])

        # Compute micro-average ROC curve and ROC area
        fpr["micro"], tpr["micro"], _ = roc_curve(y_test.ravel(), y_score.ravel())
        roc_auc["micro"] = auc(fpr["micro"], tpr["micro"])

        # Plot ROC curve
        sns.reset_orig()
        plt.clf()
        plt.figure()
        plt.plot(fpr["micro"], tpr["micro"],'--', linewidth=3,
                 label='micro-average (area = {0:0.2f})'
                 ''.format(roc_auc["micro"]))
        for i in range(n_classes):
            plt.plot(fpr[i], tpr[i], label='A-site @ {0} (area = {1:0.2f})'
                     ''.format(i+12, roc_auc[i]))

        plt.plot([0, 1], [0, 1], 'k--')
        plt.xlim([0.0, 1.0])
        plt.ylim([0.0, 1.05])
        plt.xlabel('False Positive Rate', fontsize=18)
        plt.ylabel('True Positive Rate', fontsize=18)
        plt.tick_params(axis='both', which='major', labelsize=18)
        plt.legend(loc="lower right",fontsize=12)
        plt.gcf()
        plt.savefig( self.asite_fn + ".roc.pdf")

    def reverse_complement(seq):
        seq_dict = {'A':'T','T':'A','G':'C','C':'G'}
        return "".join([seq_dict[base] for base in reversed(seq)])

    def recover_asite(self):
        ## import the predicted a-site location df
        self.testing_df_out = pd.read_table(self.testing_fn+'.predicted.txt',  header=0)

        ## adjust by the a-site location and calculate the a-site location in nt space, -1 is the missing value
        self.testing_df_out['asite_start'] = np.where( self.testing_df_out['gene_strand'] == '+',
                                                (self.testing_df_out['start'] + self.testing_df_out['asite']),
                                                (-1) ).astype(int)
        self.testing_df_out['asite_end'] = np.where(self.testing_df_out['gene_strand'] == '+',
                                                (self.testing_df_out['asite_start'] + 3),
                                                (self.testing_df_out['end'] - self.testing_df_out['asite']) ).astype(int)

        self.testing_df_out['asite_start'] = np.where(self.testing_df_out['gene_strand'] == '-',
                                                (self.testing_df_out['asite_end'] - 3),
                                                (self.testing_df_out['asite_start']) ).astype(int)

        ## use to group by command to retrieve ribosome coverage
        groupby_df = self.testing_df_out.groupby(["chrom", "asite_start", "asite_end"])
        groupby_df_count = groupby_df.size().reset_index(name="ribosome_count")

        ## left outer join the null df and the groupby_df_count to get ribsome counts at each position
        self.ribo_count_df = pd.merge( self.cds_idx_df, groupby_df_count, how = "left",
                                  on = ["chrom", "asite_start", "asite_end"] ).fillna(value=0)
        self.ribo_count_df["ribosome_count"] = self.ribo_count_df["ribosome_count"].astype(int)
        self.ribo_count_df.to_csv(path_or_buf=self.testing_fn + '.ribocount.txt', sep='\t', header=True, index=False)

        #self.testing_df_out['asite_codon']  = np.where(self.testing_df_out['strand'] == '+',
        #                                          (self.testing_df_out['read']), # [self.testing_df_out['asite']:self.testing_df_out['asite']+3]),
        #                                          ('WWW'))
        #print(self.testing_df_out)
        #slice_codon = lambda x : x['read'][x['asite']:x['asite_end']]
        #testing_df_out['asite_codon'] = testing_df_out.apply(slice_codon, axis = 1)
        #testing_df_out['asite_codon_correct']  = np.where(testing_df_out['strand'] == '+',
        #                                               testing_df_out['asite_codon'] ,
        #                                               reverse_complement (testing_df_out['asite_codon']))
        # testing_df_out['codon'] = testing_df_out['read'].str[15:18]

## ----------------------------------------
## the main work
## ----------------------------------------
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", help="input a-site file, required")
    parser.add_argument("-t", help="input testing data for the entire CDS region, required")
    parser.add_argument("-d", help="input index data-frame for the entire CDS region, required")
    parser.add_argument("-c", help="classifier to use, random forest (rf) or "
                                   "\support vector machine (svm), optional, default: rf", default="rf")

    ## check if there is any argument
    if len(sys.argv) <= 1:
        parser.print_usage()
        sys.exit(1)
    else:
        args = parser.parse_args()

    ## process the file if the input files exist
    if (args.i != None and args.t != None):
        print("[status]\tprocessing the input file: " + args.i, flush=True)
        asite_fn = args.i
        cds_fn = args.t
        cds_idx = args.d
        classifier = args.c

        print("[execute]\tplotting the a-site location distribution from " + str(asite_fn), flush=True)
        asite_loc = VisualizeAsite(asite_fn)
        asite_loc.plot()

        print("[execute]\tstart the process of a-site prediction", flush=True)
        model = TrainModel(asite_loc, cds_fn, cds_idx)

        if classifier == "rf":
            print("[execute]\tperform model training and cross validation on the training data", flush=True)
            model.rf_fit()
            print("[execute]\tplotting the bar plot of the feature importance", flush=True)
            model.rf_importance()
            print("[execute]\tpredicting the a-site from the testing data", flush=True)
            model.rf_predict()
            print("[execute]\tlocalize the a-site codon and create coverage df/vectors", flush=True)
            model.recover_asite()
        elif classifier == "svm":
            model.svm_fit()
            model.roc_curve()

        ## end
        print("[status]\tA-site module finished.", flush=True)

    else:
        print("[error]\tmissing argument", flush=True)
        parser.print_usage()
