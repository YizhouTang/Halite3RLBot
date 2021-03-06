#!/usr/bin/env python3
# Python 3.6
import os, sys
# Import the Halite SDK, which will let you interact with the game.
import hlt

# This library contains constant values.
from hlt import constants

# This library contains direction metadata to better interface with the game.
from hlt.positionals import Direction,Position

# This library allows you to generate random numbers.
import random

# Logging allows you to save messages for yourself. This is required because the regular STDOUT
#   (print statements) are reserved for the engine-bot communication.
import logging
from time import sleep,time
from math import ceil
from queue import PriorityQueue, Queue
import numpy as np

move_array = [(0,0),(1,0),(0,1),(-1,0),(0,-1)]
max_turns = {32:400,40:425,48:450,56:475,64:500}

game = hlt.Game()

bx = game.game_map.width
by = game.game_map.height

def to_tuple(p):
    return (p.x%bx,p.y%by)

dropoffs = set()

dropoffs.add(to_tuple(game.me.shipyard.position))

os.environ['TF_CPP_MIN_LOG_LEVEL'] = '2'

import tensorflow as tf
from halite_network_deploy import Model

opts = tf.GPUOptions(per_process_gpu_memory_fraction=0.1)
conf = tf.ConfigProto(gpu_options=opts)
tf.enable_eager_execution(config=conf)

model = Model()

model.load_weights('./weights/halite_model')

_ = model(np.zeros([1,bx,by,7]))

total_halite = 0

for i in range(bx):
    for j in range(by):
        total_halite += game.game_map[Position(i,j)].halite_amount


halite_per_player = total_halite/len(game.players)

target_ships = halite_per_player//1000*0.5

game.ready("MyPythonBot")

ships_last_cargo = {}

try_spawn = False

def movement_solver(ships_and_targets, game_map, block_fields, the_end = False, bases = None):
    board = [[[-1,0,0,False,[]] for x in range(game_map.width)]for y in range(game_map.height)]
    
    ship_dict = {}
    
    ship_list = []
    
    to_block = Queue()
    
    for x,y in block_fields:
        board[x][y][3] = True
    
    to_consider = set()
    
    for ship, target_preference in ships_and_targets:
        x,y= to_tuple(ship.position)
        ship_dict[ship.id] = ship
        #logging.info(str(target_preference))
        if ship.halite_amount < ceil(game_map[ship.position].halite_amount*0.1):
            board[x][y][0] = ship.id
            board[x][y][1] = 0
            board[x][y][3] = True
            
        else:
            board[x][y][0] = ship.id
            target = np.argmax(target_preference)
            #logging.info(f'target: {target}')
            board[x][y][1] = target
            if target == 0:
                board[x][y][3] = True
            else:
                to_consider.add((x,y))
                mx,my = move_array[target]
                board[(x+mx)%bx][(y+my)%by][4].append((x,y))
        
    i = 0
    
    if the_end:
        for x,y in bases:
            board[x][y][3]=False
            board[x][y][0] = -1
    
    endpoints = set()
    
    while to_consider:
        i+=1
        x,y = next(iter(to_consider))
        
        potential_block = []
        
        while not (board[x][y][0]== -1 or not board[x][y][2] == 0 or board[x][y][3]):
            to_consider.remove((x,y))
            potential_block.append((x,y))
            board[x][y][2] = i
            mx,my = move_array[board[x][y][1]]
            x, y = ((x+mx)%bx,(y+my)%by)
        
        if board[x][y][3]:
            for px, py in potential_block:
                board[px][py][3] = True
                board[px][py][1] = 0
            continue
        
        if board[x][y][0]==-1:
            #logging.info(f'added endpoint {x} {y}')
            endpoints.add((x,y))
            continue
        
        if board[x][y][2] == i:
            first_on_cycle = potential_block.index((x,y))
            if not first_on_cycle == 0:
                for px, py in potential_block[:first_on_cycle]:
                    board[px][py][3] = True
                    board[px][py][1] = 0
            
            for px, py in potential_block:
                board[px][py][3] = True
    
    def helper(x,y):
        #logging.info(f'running helper for endpoint {x} {y}')
        strings = [helper(px,py) for px,py in board[x][y][4]]
        max_len = 0
        i = 0
        index = 0
        winning_string = []
        if the_end and (x,y) in bases:
            for s in strings:
                winning_string+=s
            logging.info(f'returning string {winning_string}')
        else:
            for s in strings:
                if len(s)>max_len:
                    max_len = len(s)
                    index = i
                    winning_string = s
                    
                i+=1
        
            if len(strings)>0:
                del strings[index]
            
            for s in strings:
                for u, v in s:
                    board[u][v][3] = True
                    board[u][v][1] = 0
            
        winning_string.append((x,y))
        
        return winning_string
    
    while endpoints:
        x,y = next(iter(endpoints))
        
        endpoints.remove((x,y))
        
        winning_string = helper(x,y)[:-1]
        
        for px, py in winning_string:
            board[px][py][3] = True
        
    orders_list = []
    
    for x in range(bx):
        for y in range(by):
            ship_id = board[x][y][0]
            move = board[x][y][1]
            
            if not ship_id == -1:
                orders_list.append(ship_dict[ship_id].move(move_array[move]))
                if not board[x][y][3]:
                    logging.info(f"what {x} {y}")
    
    return orders_list


def desired_return_pathing(map,dropoffs):
    
    global bx
    global by
    
    map_representation = [[None for x in range(by)]for y in range(bx)]
    
    logging.info(len(map_representation))
    
    q = PriorityQueue()
    visited = set()
    
    for d in dropoffs:
        q.put((0,0,d,0))
    
    

    counter = 0

    #logging.info("assigned targets:")

    #old_t = time()

    while not q.empty():
        counter+=1
        cost,distance,pos,move_direction = q.get()
        if pos in visited:
            continue
        
        visited.add(pos)
        
        position = Position(pos[0],pos[1])
        #logging.info(position)
        map_representation[position.x%bx][position.y%by] = (cost-map[position].halite_amount*0.1,
                                                        distance,
                                                        map[position].halite_amount,
                                                        move_direction)
        
        
        move_cost = ceil(map[position].halite_amount*0.1)
        for i in range(4):
            x = position.directional_offset(move_array[i+1])
            if (x.x%bx,x.y%by) not in visited:
                q.put((cost+map[x].halite_amount*0.2+3.0,distance+1,(x.x%bx,x.y%by),(i+2)%4+1))

    logging.info("iterations {}".format(str(counter)))
    
    return map_representation

return_pathing = None
refresh_return = False

while True:
    # This loop handles each turn of the game. The game object changes every turn, and you refresh that state by
    #   running update_frame().
    game.update_frame()
    # You extract player metadata and the updated map metadata here for convenience.
    me = game.me
    game_map = game.game_map
    
    shipdict = {}
    
    game_end = False
    
    if max_turns[bx]-game.turn_number<=bx/2:
        game_end = True
    
    
    if game.turn_number%20 == 1 or refresh_return or game_end:
        refresh_return = False
        return_pathing = desired_return_pathing(game_map,dropoffs)
    
    for ship in me.get_ships():
        shipdict[ship.id] = ship
    
    board = np.zeros([1,bx,bx,7])
    
    game_progress = game.turn_number/max_turns[bx]*100
    
    for i in range(bx):
        for j in range(by):
            
            cell = game_map[Position(i,j)]
            
            s = []
            
            if (i,j) in dropoffs:
                s+=[1000]
            else:
                s+=[0]
            
            if cell.is_occupied:
                ship = cell.ship
                if ship.owner == me.id:
                    
                    s += [1000, 0]
                else:
                    s += [0, 1000]
                
                s += [ship.halite_amount]
            else:
                s += [0, 0, 0]
                
            s += [cell.halite_amount] +[return_pathing[i][j][0]] + [game_progress]
            
            board[0,i,j] = s
            #pipe_out.flush()
    
    padded = np.asarray(board,dtype=np.float32)
    
    #with tf.device("CPU:0"):
    policy, values = model(padded)
    
    probs = policy[0].numpy()
    
    action = []
    
    for s in me.get_ships():
        position = to_tuple(s.position)
        pr = probs[position]
        pr = pr/np.sum(pr)
        
        logging.info(str(pr))
        
        t = np.random.choice((0,1,2,3,4,5),p=pr)
        logging.info(t)
        #else:
        #    t = np.random.choice((0,1,2,3,4,5))
        act = [0]*6
        act[t] = 1
        action.append([s.id]+act)
    
    
    ready_commands = []
    
    orders_list = []
    
    block_fields = []
    
    real_halite_amount = me.halite_amount
    #while len(in_data)== 0:
    #    in_data = pipe_in.readline().strip()
    
    selected_ship = None
    #print(len(dropoffs))
    if len(me.get_ships()) < len(dropoffs)*15:
        if (len(me.get_ships())<target_ships/2 and game.turn_number<max_turns[bx]/4*3) or (len(me.get_ships())<target_ships and game.turn_number<max_turns[bx]/2):
            try_spawn = True
    else:
        max_dist = 0
        
        for s in list(me.get_ships()):
            closest = 10000
            for x,y in dropoffs:
                p = Position(x,y)
                dist = game_map.calculate_distance(s.position,p)
                closest = min(closest,dist)
            if closest>max_dist:
                selected_ship = s
                max_dist = closest
                
                     
        
    ship_dropped = -1
    
    for i in range(len(me.get_ships())):
        data = action[i]
        
        ship = shipdict[int(data[0])]
        returning = int(data[1])
        values = [float(x) for x in data[2:]]
        logging.info(str(values))
        if game_end:
            returning = 1
        
        if selected_ship and ship.id == selected_ship.id and not game_map[ship.position].has_structure and real_halite_amount >= constants.DROPOFF_COST and not game_end:
            ship_dropped = ship.id
            ready_commands.append(ship.make_dropoff())
            dropoffs.add(to_tuple(ship.position))
            real_halite_amount -= 4000
            refresh_return = True
            continue
        
        if returning == 1:
            
            _,_,_,direction = return_pathing[ship.position.x%bx][ship.position.y%by]
            move_value = [0]*5
            
            move_value[direction] = 1
            '''
            for i in range(5):
                a,b = move_array[i]
                move_cost,distance,_ = 
                
                #that won't exactly work, but let's assume it does
                
                move_value[i] = max((ship.halite_amount-move_cost),0)*(stop_distance-distance)/(stop_distance+0.01) 
            
            if max(move_value)==0:
                move_value[0] = 1
                
            if game_end and not to_tuple(ship.position) in dropoffs and move_value[0]==1:
                move_value[0] = 0
                
                min_dist = 1000
                best_move = 0
                for i in range(5):
                    a,b = move_array[i]
                    dist = game_map.calculate_distance(ship.position.directional_offset((a,b)),me.shipyard.position)
                    if dist<min_dist:
                        min_dist = dist
                        best_move = i
                
                move_value[i] = 1
            '''
            #logging.info("ship "+str(ship.id)+" returning in dir "+str(np.argmax(move_value)))
            orders_list.append((ship,move_value))
        else:
            orders_list.append((ship,values))
    
    spawning_ship = False
    
    if try_spawn and real_halite_amount >= constants.SHIP_COST and not game_map[me.shipyard].is_occupied and not game_end:
        try_spawn = False
        spawning_ship = True
    
    if spawning_ship:
        block_fields.append((me.shipyard.position.x,me.shipyard.position.y))
    
    command_queue = movement_solver(orders_list,game_map,block_fields,game_end,dropoffs)
    
    if spawning_ship:
        command_queue.append(game.me.shipyard.spawn())
    
    command_queue += ready_commands
    # Send your moves back to the game environment, ending this turn.
    game.end_turn(command_queue)
