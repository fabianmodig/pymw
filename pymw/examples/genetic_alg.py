#!/usr/bin/env python

from pymw import *
import time
from optparse import OptionParser
import math
import random

def fitness_func(ind):
    return reduce(lambda x, y: x+y, ind)

def mutate(ind, mut_rate):
    for i in range(len(ind)):
        if random.random() < mut_rate:
            ind[i] = 1-ind[i]

def select(fitness, ind_set):
    total_fit = reduce(lambda x, y: x+y, fitness)
    spin_val = random.random()*total_fit
    ind = 0
    while spin_val >= 0:
        spin_val -= fitness[ind]
        ind += 1
    return ind_set[ind-1]

def crossover(ind1, ind2):
    cpt = random.randint(0,len(ind1))
    new_ind1 = ind1[:cpt]+ind2[cpt:]
    new_ind2 = ind2[:cpt]+ind1[cpt:]
    
    return new_ind1, new_ind2

def perform_ga(randseed, mut_rate, num_gens, cross_rate, ind_set):
    random.seed(randseed)
    num_inds = len(ind_set)
    for gen in range(num_gens):
        fitness = [fitness_func(ind) for ind in ind_set]
        total_fit = reduce(lambda x, y: x+y, fitness)
        avg_fit = total_fit/len(ind_set)
        max_fit = reduce(lambda x, y: max(x,y), fitness)
        new_ind_set = []
        num_crossovers = num_inds*cross_rate
        for i in range(num_inds/2):
            parent1 = select(fitness, ind_set)
            parent2 = select(fitness, ind_set)
            if random.random() < cross_rate:
                child1, child2 = crossover(parent1, parent2)
                mutate(child1, mut_rate)
                mutate(child2, mut_rate)
                new_ind_set.append(child1)
                new_ind_set.append(child2)
            else:
                new_ind_set.append(parent1)
                new_ind_set.append(parent2)
        ind_set = new_ind_set
    
    return [max_fit, ind_set]


parser = OptionParser(usage="usage: %prog")
parser.add_option("-i", "--interface", dest="interface", default="multicore", help="specify the interface (multicore/mpi/boinc)", metavar="INTERFACE")
parser.add_option("-n", "--num_workers", dest="n_workers", default="4", help="number of workers", metavar="N")
parser.add_option("-p", "--project_home", dest="p_home", default="", help="directory of the project (BOINC interface)", metavar="DIR")
options, args = parser.parse_args()

n_workers = int(options.n_workers)

start_time = time.time()

if options.interface == "multicore":
    interface_obj = pymw.interfaces.multicore.MulticoreInterface(num_workers=n_workers)
elif options.interface == "mpi":
    interface_obj = pymw.interfaces.mpi.MPIInterface(num_workers=n_workers)
elif options.interface == "boinc":
    interface_obj = pymw.interfaces.boinc.BOINCInterface(project_home=options.p_home)
else:
    print "Interface", options.interface, "unknown."
    exit()

pymw_master = pymw.PyMW_Master(interface=interface_obj)

post_init_time = time.time()

num_inds = 20
gene_len = 100
num_gens = 10
mut_rate = 1./gene_len
cross_rate = 0.7

gene_pool = [[random.randint(0,1) for i in range(gene_len)] for n in range(int(2*n_workers*num_inds))]

num_active_tasks = 0
max_fitness = 0

for q in range(n_workers):
    ind_set = random.sample(gene_pool, num_inds)
    for x in ind_set: gene_pool.remove(x)
    pymw_master.submit_task(perform_ga, 
                            input_data=(random.random(), mut_rate, num_gens, cross_rate, ind_set,),
                            modules=("random",),
                            dep_funcs=(crossover, select, mutate, fitness_func,))
    
#while max_fitness < gene_len:
gen_count = 0
while gen_count < (1000*n_workers)/num_gens:
    gen_count += 1
    old_max = max_fitness
    try:
        res_task, res = pymw_master.get_result()
    except:
        exit()
    max_fitness = max(max_fitness, res[0])
    gene_pool.extend(res[1])
    
    ind_set = random.sample(gene_pool, num_inds)
    for x in ind_set: gene_pool.remove(x)
    pymw_master.submit_task(perform_ga, 
                            input_data=(random.random(), mut_rate, num_gens, cross_rate, ind_set,),
                            modules=("random",),
                            dep_funcs=(crossover, select, mutate, fitness_func,))

fitness = [fitness_func(ind) for ind in gene_pool]
avg_fit = reduce(lambda x, y: x+y, fitness)/len(gene_pool)
print max_fitness, avg_fit

end_time = time.time()

print "Number of workers:", str(n_workers)
print "Calculation time:", str(end_time-start_time)
print "Total time:", str(end_time-start_time)
