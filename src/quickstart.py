import os
import time
import random
import vizdoom as vzd


game = vzd.DoomGame()

game.load_config(
    os.path.join(vzd.scenarios_path, "basic.cfg")
)

game.set_window_visible(True)

game.init()


print(game.get_available_buttons())

actions = [
    [1, 0, 0],
    [0, 1, 0],
    [0, 0, 1],
    [0, 0, 0]
]

game.new_episode()

while not game.is_episode_finished():
    state = game.get_state()
    print("State Number: ", state.number)
    print("Game variables: ", state.game_variables)

    action = random.choice(actions)
    reward = game.make_action(action)

    print("Action: ", action)
    print("Reward: ", reward)
    print("========================")

    time.sleep(0.05)

print("Episode finished!")
print("Total reward: ", game.get_total_reward())
print("========================")
    

game.close()

