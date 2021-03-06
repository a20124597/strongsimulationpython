import graph_tool.all as gt
import networkx as nx
import metis
import time
import dualsimulation as ds
from mpi4py import MPI
import numpy as np
import os
import View as vie
import globalvar as gl
# mpiexec -np 3 python strongsimulation_paralle.py
# mpiexec -np 3 python strongsimulation_paralle.py
_DEBUG = False
import BFS as bfs
import dualsimulation_paralle as dsp
import alg_strongsim_opt as ss
class StrongWorker:
    remove_pred = {}
    remove_succ = {}
    sim={}
    out_messages=[]
    in_messages= []
    sim_counter_post =[]
    sim_counter_pre = []
    t_f = {}
    con_run =0
    sim_node_set =set()
    sim_edge_set =set()
    d_hop_node ={}
    def __init__(self):
        self.out_messages=[]
        self.in_messages= []
        for i in xrange(0,gl.worker_num):
            self.out_messages.append([])
            self.in_messages.append([])
        self.remove_pred = {}
        self.remove_succ = {}
        self.sim={}
        self.sim_counter_post =[]
        self.sim_counter_pre = []
        self.t_f = {}
        self.con_run =0
        self.sim_node_set = set()
        self.sim_edge_set =set()
        self.d_hop_node ={}

    def clear(self):
        self.out_messages=[]
        self.in_messages= []
        self.remove_pred = {}
        self.remove_succ = {}
        for i in xrange(0,gl.worker_num):
            self.out_messages.append([])
            self.in_messages.append([])
        self.sim_counter_post =[]
        self.sim_counter_pre = []
        self.con_run =0
        self.t_f = {}
        self.sim ={}
        self.sim_node_set = set()
        self.sim_edge_set =set()
        self.d_hop_node ={}

    def dual_sim_initialization(self,Qgraph,Dgraph,initialized_sim):
        pred_dgraph_vertices = set(int(v) for v in Dgraph.vertices() if v.out_degree() != 0)
        succ_dgraph_vertices = set(int(v) for v in Dgraph.vertices() if v.in_degree() != 0)
        for u in Qgraph.vertices():
            if initialized_sim == False:
                if u.out_degree() == 0 and u.in_degree() == 0:
                    self.sim[int(u)] = set(int(v) for v in Dgraph.vertices() if Qgraph.vertex_properties["label"][u] == Dgraph.vertex_properties["label"][v])
                elif u.out_degree() != 0 and u.in_degree() == 0:
                    self.sim[int(u)] = set(int(v) for v in Dgraph.vertices() if Qgraph.vertex_properties["label"][u] == Dgraph.vertex_properties["label"][v] and v.out_degree() != 0)
                elif u.out_degree() ==0 and u.in_degree() != 0:
                    self.sim[int(u)] = set(int(v) for v in Dgraph.vertices() if Qgraph.vertex_properties["label"][u] == Dgraph.vertex_properties["label"][v] and v.in_degree() != 0)
                else:
                    self.sim[int(u)] = set(int(v) for v in Dgraph.vertices() if Qgraph.vertex_properties["label"][u] == Dgraph.vertex_properties["label"][v] and v.out_degree() != 0 and v.in_degree() != 0)
                for v in gl.outer_node:
                    if v in Dgraph.vertices() and Qgraph.vertex_properties["label"][u] == Dgraph.vertex_properties["label"][v]:
                        self.sim[int(u)].add(int(v))
            self.remove_pred[int(u)] = pred_dgraph_vertices.difference(set(int(v) for w in self.sim[int(u)] for v in Dgraph.vertex(w).in_neighbors())) #all node do not have u child
            self.remove_succ[int(u)] = succ_dgraph_vertices.difference(set(int(v) for w in self.sim[int(u)] for v in Dgraph.vertex(w).out_neighbors()))# all node do not have u parent

    def remap_data_id(self,Dgraph):
        '''
        Remap vertex id of nodes in dgraph (ball_view) to the range [0, num_vertex) via dict t_f (true_id --> fake_id);
        '''
        fid = 0
        for v in Dgraph.vertices():
            self.t_f[int(v)] = fid
            fid = fid + 1
    #        assert fid <= dgraph.num_vertices()
    def dual_counter_initialization(self,Qgraph, Dgraph):
        '''
        Initialize the 2-dimensional list sim_counter_post and sim_counter_pre such that
        sim_counter_post[v][u] = |post(v) \cap sim(u)|
        sim_counter_pre[v][u] = |pre(v) \cap sim(u)|
        '''
    #    global Qgraph
    #    global Dgraph
        self.sim_counter_post = [[0 for col in xrange(0, Qgraph.num_vertices())] for row in xrange(0, Dgraph.num_vertices())]
        self.sim_counter_pre = [[0 for col in xrange(0, Qgraph.num_vertices())] for row in xrange(0, Dgraph.num_vertices())]
        for w in Dgraph.vertices():
            for u in Qgraph.vertices():
                self.sim_counter_post[self.t_f[int(w)]][int(u)] = len(set(w.out_neighbors()).intersection(self.sim[u]))
                self.sim_counter_pre[self.t_f[int(w)]][int(u)] = len(set(w.in_neighbors()).intersection(self.sim[u]))
    def update_sim_counter(self,u, v,dgraph):
        '''
        '''
        w = dgraph.vertex(v)
        for wp in w.in_neighbors():
            if self.sim_counter_post[self.t_f[int(wp)]][u] > 0:
                self.sim_counter_post[self.t_f[int(wp)]][u] = self.sim_counter_post[self.t_f[int(wp)]][u] - 1
        for ws in w.out_neighbours():
            if self.sim_counter_pre[self.t_f[int(ws)]][u] > 0:
                self.sim_counter_pre[self.t_f[int(ws)]][u] = self.sim_counter_pre[self.t_f[int(ws)]][u] -1

    def find_nonempty_remove(self,Qgraph):
        '''
        Return (the first) u if remove_pred/succ[u] is not empty. Otherwise return None.
        '''
    #    global Qgraph
        for u in Qgraph.vertices():
            if len(self.remove_pred[int(u)]) !=  0:
                return u
            if len(self.remove_succ[int(u)]) != 0:
                return u

        return None

    def dual_sim_refinement(self,qgraph, dgraph):
        '''
        Decrementally refine sim untile all remove sets are all empty.
        '''
    #    global Qgraph
    #    global Dgraph
        #a counter used to speedup the refinement
        #note that if the memory of your machine is relative small, you can (c)pickle it to harddisk in order to save memory

        #First remap vertex indices of nodes in dgraph to the range [0, dgraph.num_vertices())
        #Then initialize counters using the fake indices
        u = self.find_nonempty_remove(qgraph)
        while u != None:
            #a set of assertions
            #Assertion1: for all u, remove_pred[u] == pre(prevsim[u]) \ pre(sim[u])
            #Assertion2: for all u, remove_succ[u] == succ(prevsim[u]) \ succ(sim[u])
    #        for ass_u in qgraph.vertices():
    #            assert assert_check(remove_pred[ass_u], set(v for w in prevsim[ass_u] for v in w.in_neighbours()).difference(set(v for w in sim[ass_u] for v in w.in_neighbours()))) is True
    #            assert assert_check(remove_succ[ass_u], set(v for w in prevsim[ass_u] for v in w.out_neighbours()).difference(set(v for w in sim[ass_u] for v in w.out_neighbours()))) is True

            if len(self.remove_pred[int(u)]) != 0: #all node do not have u label as child
                for u_p in u.in_neighbors():
                    for w_pred in self.remove_pred[int(u)]:
                        if  w_pred in self.sim[int(u_p)] and w_pred not in gl.outer_node:
                            self.sim[int(u_p)].discard(w_pred)
                            if gl.msg_through_node_distance.has_key(w_pred):
                                for i in gl.msg_through_node_distance[w_pred]:
                                    if i!=gl.worker_id:
                                        self.out_messages[i].append((w_pred,int(u_p)))
                            self.update_sim_counter(int(u_p), w_pred,dgraph)
                            for w_pp in dgraph.vertex(w_pred).in_neighbors():
                                if self.sim_counter_post[self.t_f[int(w_pp)]][int(u_p)] == 0:
                                    #check whether post(w_pp) \cap sim[u_p] == \emptyset
                                    self.remove_pred[int(u_p)].add(int(w_pp))
                            for w_ps in dgraph.vertex(w_pred).out_neighbors():
                                if self.sim_counter_pre[self.t_f[int(w_ps)]][int(u_p)] == 0:
                                    #check whether pre(w_ps) \cap sim[u_p] == \emptyset
                                    self.remove_succ[int(u_p)].add(int(w_ps))
                                    # if int(u_p) ==2 and int(w_ps) ==548:
                                    #     print "a"
                if _DEBUG == True:
                    import pdb
                    pdb.set_trace()
    #           prevsim[u] = set(v for v in sim[u]) #prevsim[u] is a hardcopy of sim[u]
                self.remove_pred[int(u)].clear()

            if len(self.remove_succ[int(u)]) != 0:
                for u_s in u.out_neighbors():
                    for w_succ in self.remove_succ[int(u)]:
                        if w_succ in self.sim[int(u_s)] and w_succ not in gl.outer_node:
                            self.sim[int(u_s)].discard(w_succ)
                            if gl.msg_through_node_distance.has_key(w_succ):
                                for i in gl.msg_through_node_distance[w_succ]:
                                    if i !=gl.worker_id:
                                        self.out_messages[i].append((w_succ,int(u_s)))
                            self.update_sim_counter(int(u_s), w_succ,dgraph)
                            for w_sp in dgraph.vertex(w_succ).in_neighbors():
                                if self.sim_counter_post[self.t_f[int(w_sp)]][int(u_s)] == 0:
                                    #check whether post(w_sp) \cap sim[u_s] == \emptyset
                                    self.remove_pred[int(u_s)].add(int(w_sp))
                            for w_ss in dgraph.vertex(w_succ).out_neighbors():
                                if self.sim_counter_pre[self.t_f[int(w_ss)]][int(u_s)] == 0:
                                    #check whether pre(w_ss) \cap sim[u_s] == \emptyset
                                    self.remove_succ[int(u_s)].add(int(w_ss))
                                    # if int(u_s) ==2 and int(w_ss) == 548:
                                    #     print "b"
                if _DEBUG == True:
                    import pdb
                    pdb.set_trace()
    #            prevsim[u] = set(v for v in sim[u]) #prevsim[u] is a hardcopy of sim[u]
                self.remove_succ[int(u)].clear()

            u = self.find_nonempty_remove(qgraph)

    def send_messages(self):
        for i in xrange(0,gl.worker_num):
            partner = (i - gl.worker_id +gl.worker_num) % gl.worker_num
            if partner != gl.worker_id:
                if gl.worker_id < partner :
                    gl.comm.send(self.out_messages[partner], dest=partner, tag=0)
                    self.in_messages[partner] = gl.comm.recv(source=partner, tag=0)
                else :
                    self.in_messages[partner] = gl.comm.recv(source=partner, tag=0)
                    gl.comm.send(self.out_messages[partner], dest=partner, tag=0)

    def clear_messages(self):
        self.out_messages = []
        self.in_messages = []
        for i in xrange(0,gl.worker_num):
            self.out_messages.append([])
            self.in_messages.append([])

    def pEval(self,qgraph,dgraph):
        self.dual_sim_initialization(qgraph,dgraph,False)
        self.remap_data_id(dgraph)
        self.dual_counter_initialization(qgraph,dgraph)
        self.dual_sim_refinement(qgraph,dgraph)
        for u in qgraph.vertices():
            for v in gl.border_node:
                if v in dgraph.vertices() and qgraph.vertex_properties["label"][u] == dgraph.vertex_properties["label"][v] and int(v) not in self.sim[int(u)]:
                    if gl.msg_through_node_distance.has_key(int(v)):
                                for i in gl.msg_through_node_distance[int(v)]:
                                    if i!=gl.worker_id:
                                        self.out_messages[i].append((int(v),int(u)))
        self.send_messages()

    def dual_sim_output(self,qgraph):
        '''
        Output the matching relation if exists
        '''
    #    global Qgraph
        if self.match_check(qgraph) == True:
            return self.sim
        else:
            self.sim =None
            return None

    def match_check(self,qgraph):
        '''
        Check whether sim is a matching relation.
        '''
        for u in qgraph.vertices():
            if len(self.sim[u]) == 0:
                return False

        return True

    def is_continue(self):
        for i in xrange(0,gl.worker_num):
            if self.in_messages[i]:
                self.con_run =1
                break
        buf = np.array([self.con_run])
        gl.comm.Barrier()
        gl.comm.Allreduce(MPI.IN_PLACE,buf,MPI.SUM)
        # print "message count",buf[0],self.worker_id

        if buf[0]>0:
            self.con_run = 0
            return True
        else:
            return False

    def incEval(self,qgraph,dgraph):
        for i in xrange(0,len(self.in_messages)):
            for triple in self.in_messages[i]:
                u = triple[1]
                w = triple[0]
                if w in self.sim[u]:
                    self.sim[u].discard(w)
                    self.update_sim_counter(u, w,dgraph)
                    for w_pp in dgraph.vertex(w).in_neighbors():
                        if self.sim_counter_post[self.t_f[int(w_pp)]][u] == 0:
                                    #check whether post(w_pp) \cap sim[u_p] == \emptyset
                            self.remove_pred[u].add(int(w_pp))
                    for w_ps in dgraph.vertex(w).out_neighbors():
                        if self.sim_counter_pre[self.t_f[int(w_ps)]][u] == 0:
                                #check whether pre(w_ps) \cap sim[u_p] == \emptyset
                            self.remove_succ[u].add(int(w_ps))
        self.clear_messages()
        self.dual_sim_refinement(qgraph,dgraph)
        self.send_messages()

    def write_two_result_to_txt(self,sim1,sim2,filename):
        f = open(filename, 'w')
        for key in sim1.keys():
            line1 = ""
            line2 =""
            for v1 in sim1[key]:
                line1 +=str(v1)+"   "
            for v2 in sim2[int(key)]:
                line2 +=str(v2)+"   "
            line1 +="\n"
            line2 +="\n"
            f.write(line1)
            f.write(line2)
            f.write("========\n")
        f.close()

    def write_one_result_to_txt(self,sim1,filename):
        f = open(filename, 'w')
        for key in sim1.keys():
            line1 = ""
            for v1 in sim1[key]:
                line1 +=str(v1)+"   "
            line1 +="\n"
            f.write(line1)
        f.close()

    def output_step_data(self,dgraph,path):
        vmatch_set = set()
        for key in self.sim.keys():
            for v in self.sim[key]:
                vmatch_set.add(v)
        gtview = gt.GraphView(dgraph, vfilt = lambda v: v in vmatch_set)
        gtview.vertex_properties["show"] = gtview.new_vertex_property("string")
        for v in gtview.vertices():
            if v in self.border_node:
                tmpstr = "o"+str(v)+gtview.vertex_properties["label"][v]
            else:
                tmpstr = str(v)+gtview.vertex_properties["label"][v]
            gtview.vertex_properties["show"][v] =tmpstr
        gt.graph_draw(gtview, vertex_text = gtview.vertex_properties["show"],output_size=(800, 800),output = path)
        del gtview.vertex_properties["show"]

    def draw_graph_label_id(self,dgraph,path):
        dgraph.vertex_properties["show"] = dgraph.new_vertex_property("string")
        for v in dgraph.vertices():
                if v in self.border_node:
                    tmpstr = "o"+str(v)+dgraph.vertex_properties["label"][v]
                else:
                    tmpstr = str(v)+dgraph.vertex_properties["label"][v]
                dgraph.vertex_properties["show"][v] =tmpstr
        gt.graph_draw(dgraph, vertex_text = dgraph.vertex_properties["show"],output_size=(800, 800),output = path)
        del dgraph.vertex_properties["show"]

    def dual_sim_is_same(self,sim1,sim2):
        for key in sim1.keys():
            if int(key) not in sim2.keys():
                return False
            elif len(sim1[key])!=len(sim2[int(key)]):
                return False
            else:
                for v in sim1[key]:
                    if int(v) not in sim2[int(key)]:
                        return False
        return True

    def sim_edge(self,Qgraph,Dgraph,simMatchResult):
        edge_set=set()
        for e in Qgraph.edges():
            eSet=set()
            source=e.source()
            target=e.target()
            simsource=simMatchResult[source]
            simtarget=simMatchResult[target]
            if(len(simsource)==0 or len(simtarget)==0):
                eSet.clear()
                break
            for sourcev in simsource:
                for targetv in simtarget:
                    eg=Dgraph.edge(sourcev,targetv)
                    if eg:
                        eSet.add(eg)
            edge_set|=eSet
        return edge_set

    def cal_diameter_qgraph(self,qgraph):
        '''
        Calculate the diameter of qgraph
        '''
        #ug=gt.Graph(qgraph)
        #ug.set_directed(False)
        temp_dia = 0
        max_dia = qgraph.num_vertices()-1
        for u in qgraph.vertices():
            dist = gt.shortest_distance(qgraph, u, None, None, None,None,False)
            for i in xrange(0, len(dist.a)):
                if dist.a[i] <= max_dia and temp_dia < dist.a[i]:
                    temp_dia = dist.a[i]
        return temp_dia

    def dual_paraller(self,Qgraph,Dgraph):
            self.pEval(Qgraph,Dgraph)
            gl.comm.Barrier()
            while(self.is_continue()):
                self.incEval(Qgraph,Dgraph)
                gl.comm.Barrier()
            gl.comm.Barrier()
            # sim_result ={}
            # all_result = None
            # if gl.worker_id == 0:
            #     all_result=gl.comm.gather(self.sim, root=0)
            # else:
            #     gl.comm.gather(self.sim, root=0)
            # if gl.worker_id ==0:
            #     for u in Qgraph.vertices():
            #         sim_result[int(u)] =set()
            #     for part in all_result:
            #         if part == None:
            #             continue
            #         for key in part.keys():
            #             sim_result[key] |= part[key]
            # return sim_result

    def set_is_same_set(self,set1,set2):
        if(len(set1)!=len(set2)):
            return False
        for v in set1:
            if v not in set2:
                return False
        return True

    def strong_paraller(self,Qgraph,Dgraph):
            d_Q = self.cal_diameter_qgraph(Qgraph)
            self.dual_paraller(Qgraph,Dgraph)
            for u in Qgraph.vertices():
                for v in self.sim[int(u)]:
                    self.sim_node_set.add(v)
            self.sim_edge_set = self.sim_edge(Qgraph,Dgraph,self.sim)
            dual_graph = gt.GraphView(Dgraph, vfilt = lambda v: v in self.sim_node_set,efilt = lambda  e: e in self.sim_edge_set)
            gl.comm.Barrier()
            all_sim_node = set()
            all_result =None
            if gl.worker_id == 0:
                all_result=gl.comm.gather(self.sim_node_set, root=0)
            else:
                gl.comm.gather(self.sim_node_set, root=0)
            if gl.worker_id ==0:
                for node_set in all_result:
                    all_sim_node |=node_set
            all_sim_node = gl.comm.bcast(all_sim_node if gl.worker_id == 0 else None, root=0)
            # print all_sim_node
            gl.comm.Barrier()
            for v in all_sim_node:
                bfs_work=bfs.BfsWorker()
                bfs_work.bfs_paraller(Dgraph,v,d_Q)
                self.d_hop_node[v] = set(bfs_work.result_node & self.sim_node_set)
                gl.comm.Barrier()
            gl.comm.Barrier()
            all_strong_node =set()

            for node in all_sim_node:
                tmp_view=gt.GraphView(dual_graph, vfilt = lambda v: v in self.d_hop_node[node])
                dwork = dsp.DualWorker()
                dwork.dual_paraller(Qgraph,tmp_view)
                for u in Qgraph.vertices():
                    all_strong_node |= dwork.sim[int(u)]
                gl.comm.Barrier()
            all_paraller_strong_node =set()
            all_result =None
            if gl.worker_id == 0:
                all_result=gl.comm.gather(all_strong_node, root=0)
            else:
                gl.comm.gather(all_strong_node, root=0)
            if gl.worker_id ==0:
                for node_set in all_result:
                    all_paraller_strong_node |=node_set
            if gl.worker_id ==0:
                direct_node_set=set()
                balllistsim=ss.strong_simulation_ball(Qgraph,Dgraph)
                for ball in balllistsim:
                    for v in ball.vertices():
                        direct_node_set.add(int(v))
                print self.set_is_same_set(all_paraller_strong_node,direct_node_set)



if __name__ == "__main__":
    gl.comm = MPI.COMM_WORLD
    gl.worker_id = gl.comm.Get_rank()
    gl.worker_num = gl.comm.Get_size()
    Dgraph = gt.load_graph("ci6/data1/Dgraph.xml.gz")
    if gl.worker_id ==0:
        gl.partion_dgraph("ci6/data1/Dgraph.xml.gz")
    gl.id2block = gl.comm.bcast(gl.id2block if gl.worker_id == 0 else None, root=0)
    gl.comm.Barrier()
    gl.LocalGraph = gl.load_local_graph(Dgraph)
    # if gl.worker_id ==0:
    #     print gl.id2block[867]
    index=1
    while index<100:
        q_file ="ci6/data"+str(index)+"/Qgraph.xml.gz"
        Qgraph = gt.load_graph(q_file)
        strong_worker = StrongWorker()
        print index,
        strong_worker.strong_paraller(Qgraph,Dgraph)
        index +=1